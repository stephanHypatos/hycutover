import time
import unicodedata
import urllib.parse

import pandas as pd
import requests
import streamlit as st
from auth import HypatosAPI
from helpers import (
    clear_session_state_generic,
    get_source_base_url,
    get_target_base_url,
    input_credentials,
    validate_scopes,
)

st.set_page_config(page_title="Copy Documents", page_icon=":card_index:")

_RETRY_DELAYS_S = [20, 20, 20, 20, 20, 20]  # 6 attempts × 20s = 120s max


# ---------------------------------------------------------------------------
# Auth (same pattern as 1_Clone_Projects.py)
# ---------------------------------------------------------------------------

def _authenticate():
    source_user = st.session_state.get("sourcecompany_user", "")
    source_pw = st.session_state.get("sourcecompany_apipw", "")
    target_user = st.session_state.get("targetcompany_user", "")
    target_pw = st.session_state.get("targetcompany_apipw", "")
    source_base_url = get_source_base_url()
    target_base_url = get_target_base_url()

    errors = False
    if not source_user or not source_pw:
        st.error("Please provide Source Company credentials.")
        errors = True
    if not target_user or not target_pw:
        st.error("Please provide Target Company credentials.")
        errors = True
    if errors:
        return

    source_auth = HypatosAPI(source_user, source_pw, source_base_url)
    target_auth = HypatosAPI(target_user, target_pw, target_base_url)

    if source_auth.authenticate():
        if validate_scopes(source_auth, "Source Company"):
            company = source_auth.get_company_info()
            if company:
                st.session_state["source_company_name"] = company.get("name", "Unknown")
                st.info(f"Source Company: **{st.session_state['source_company_name']}**")
                st.session_state["source_auth"] = source_auth
                st.success("Source Authentication succeeded!")
            else:
                st.error("Source authenticated but company details could not be fetched.")
                st.session_state.pop("source_auth", None)
        else:
            st.session_state.pop("source_auth", None)
    else:
        st.error(f"Source Authentication failed: {source_auth.last_error or 'Unknown error'}")

    if target_auth.authenticate():
        if validate_scopes(target_auth, "Target Company"):
            company = target_auth.get_company_info()
            if company:
                st.session_state["target_company_name"] = company.get("name", "Unknown")
                st.info(f"Target Company: **{st.session_state['target_company_name']}**")
                st.session_state["target_auth"] = target_auth
                st.success("Target Authentication succeeded!")
            else:
                st.error("Target authenticated but company details could not be fetched.")
                st.session_state.pop("target_auth", None)
        else:
            st.session_state.pop("target_auth", None)
    else:
        st.error(f"Target Authentication failed: {target_auth.last_error or 'Unknown error'}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_filename(name: str) -> str:
    """NFC-normalize a filename so it fits in a Latin-1 HTTP header."""
    nfc = unicodedata.normalize("NFC", name)
    try:
        nfc.encode("latin-1")
        return nfc
    except UnicodeEncodeError:
        return urllib.parse.quote(nfc)


def _parse_doc_ids(excel_file) -> list:
    """
    Read document IDs from the first column of an Excel file.
    Skips any header row if the first value does not look like an ID.
    """
    df = pd.read_excel(excel_file, header=None, dtype=str)
    values = df.iloc[:, 0].dropna().str.strip().tolist()
    # Drop header-like values: IDs are typically 24-char hex or 36-char UUIDs
    return [v for v in values if len(v) >= 20 and " " not in v]


def _find_doc_by_file_id(target_auth, main_file_id: str):
    """
    Query GET /documents?fileId={main_file_id} with up to 6 retries at 20s
    intervals (20s, 40s, 60s, 80s, 100s, 120s cumulative).
    Returns the first matching document dict, or None on timeout.
    """
    for attempt, delay in enumerate(_RETRY_DELAYS_S, 1):
        cumulative = sum(_RETRY_DELAYS_S[:attempt])
        st.write(f"⏳ Attempt {attempt}/6 — waiting {delay}s (cumulative: {cumulative}s)…")
        time.sleep(delay)

        r = requests.get(
            f"{target_auth.base_url}/documents",
            headers=target_auth.get_headers(),
            params={"fileId": main_file_id, "limit": 5},
        )
        if r.status_code == 200:
            docs = r.json().get("data", [])
            if docs:
                return docs[0]
        else:
            st.warning(f"API returned {r.status_code} on attempt {attempt}.")

    return None


def _copy_one_document(source_doc_id: str, source_auth, target_auth, target_project_id: str):
    """
    Full copy flow for a single document ID:
      1. Fetch document metadata from source
      2. Download each file binary from source
      3. Upload each file to target → collect new fileIds
      4. Process batch in target project
      5. Poll for the new document in target
      6. POST /documents/{newId}/external-data with groundTruthDocumentId
    Returns a result dict with status and key IDs.
    """

    # Step 1 — fetch document metadata
    st.write("📋 Fetching document metadata from source…")
    r = requests.get(
        f"{source_auth.base_url}/documents/{source_doc_id}",
        headers=source_auth.get_headers(),
    )
    if r.status_code != 200:
        st.error(f"Failed to fetch document metadata: HTTP {r.status_code} — {r.text}")
        return {"status": "failed", "step": "fetch_metadata", "sourceDocId": source_doc_id}

    doc_meta = r.json()

    # Build a deduped file list anchored on the guaranteed top-level fileId.
    # doc.fileId is always the main file; doc.files[] may add attachments.
    main_file_id = doc_meta.get("fileId")
    files_array = doc_meta.get("files") or []

    seen_ids: set = set()
    files_to_download = []

    if main_file_id:
        seen_ids.add(main_file_id)
        main_type = next((f.get("type", "unknown") for f in files_array if f.get("id") == main_file_id), "invoice")
        files_to_download.append({"id": main_file_id, "type": main_type, "mainFile": True})

    for f in files_array:
        if f.get("id") and f["id"] not in seen_ids:
            seen_ids.add(f["id"])
            files_to_download.append(f)

    if not files_to_download:
        st.error("Document has no fileId and no files attached.")
        return {"status": "failed", "step": "no_files", "sourceDocId": source_doc_id}

    st.write(f"Found **{len(files_to_download)}** file(s): "
             + ", ".join(f"`{f['type']}`" for f in files_to_download))

    # Step 2 + 3 — download each file from source via GET /files/{id}, re-upload to target
    uploaded_file_ids = []
    for f in files_to_download:
        file_id = f["id"]
        file_type = f.get("type", "unknown")

        st.write(f"⬇️ Downloading `{file_type}` file (`{file_id[:8]}…`)…")
        dl = requests.get(
            f"{source_auth.base_url}/files/{file_id}",
            headers=source_auth.get_headers(),
        )
        if dl.status_code != 200:
            st.error(f"Failed to download file `{file_id}`: HTTP {dl.status_code}")
            return {"status": "failed", "step": "download_file", "fileId": file_id}

        filename = _safe_filename(dl.headers.get("X-Hy-Filename", file_id))
        content_type = dl.headers.get("Content-Type", "application/octet-stream").split(";")[0].strip()

        st.write(f"⬆️ Uploading `{filename}` to target…")
        ul_headers = target_auth.get_headers()
        ul_headers["Content-Type"] = content_type
        ul_headers["X-Hy-Filename"] = filename
        ul = requests.post(
            f"{target_auth.base_url}/files",
            data=dl.content,
            headers=ul_headers,
        )
        if ul.status_code != 201:
            st.error(f"Failed to upload file: HTTP {ul.status_code} — {ul.text}")
            return {"status": "failed", "step": "upload_file", "filename": filename}

        new_file_id = ul.json().get("id")
        uploaded_file_ids.append(new_file_id)
        st.write(f"  → new fileId: `{new_file_id}`")

    # Step 4 — process batch in target
    st.write("🔄 Submitting batch to target project…")
    batch = requests.post(
        f"{target_auth.base_url}/cases/process-file-batch",
        json={"fileIds": uploaded_file_ids, "projectId": target_project_id},
        headers=target_auth.get_headers(),
    )
    if batch.status_code not in (200, 201, 202):
        st.error(f"Batch processing failed: HTTP {batch.status_code} — {batch.text}")
        return {"status": "failed", "step": "process_batch", "uploadedFileIds": uploaded_file_ids}
    st.write("✅ Batch submitted.")

    # Step 5 — find the new document by the main fileId via GET /documents?fileId=...
    # uploaded_file_ids[0] is always the main file (anchored on source doc.fileId)
    main_uploaded_file_id = uploaded_file_ids[0]
    st.write(f"🔎 Polling for document with fileId `{main_uploaded_file_id}`…")
    new_doc = _find_doc_by_file_id(target_auth, main_uploaded_file_id)

    if new_doc is None:
        st.warning(
            "Document not found after 120s. "
            "Use the **Retry Pending** button below to try again once the document appears."
        )
        pending = st.session_state.get("pending_external_data", [])
        pending.append({"mainFileId": main_uploaded_file_id, "sourceDocId": source_doc_id})
        st.session_state["pending_external_data"] = pending
        return {"status": "partial", "step": "poll_timeout", "sourceDocId": source_doc_id, "mainFileId": main_uploaded_file_id}

    new_doc_id = new_doc["id"]
    st.write(f"✅ New document found in target: `{new_doc_id}`")

    # Step 6 — set groundTruthDocumentId
    st.write("🔗 Setting `groundTruthDocumentId`…")
    ext = requests.post(
        f"{target_auth.base_url}/documents/{new_doc_id}/external-data",
        json={"groundTruthDocumentId": source_doc_id},
        headers=target_auth.get_headers(),
    )
    if ext.status_code not in (200, 201, 202):
        st.error(f"Failed to set external data: HTTP {ext.status_code} — {ext.text}")
        return {"status": "partial", "step": "external_data", "sourceDocId": source_doc_id, "targetDocId": new_doc_id}

    st.success(f"✅ Copied: `{source_doc_id}` → `{new_doc_id}`")
    return {"status": "success", "sourceDocId": source_doc_id, "targetDocId": new_doc_id}


# ---------------------------------------------------------------------------
# Main section
# ---------------------------------------------------------------------------

def _copy_documents_section():
    source_auth = st.session_state["source_auth"]
    target_auth = st.session_state["target_auth"]

    col_src, col_tgt = st.columns(2)

    with col_src:
        st.subheader("Source Project")
        source_data = source_auth.get_projects()
        source_projects = source_data.get("data", []) if source_data else []
        if not source_projects:
            st.error("No projects found in source company.")
            return
        source_project = st.selectbox(
            "Select Source Project",
            [(p["id"], p["name"]) for p in source_projects],
            format_func=lambda x: x[1],
            key="copy_docs_source_project",
        )

    with col_tgt:
        st.subheader("Target Project")
        target_data = target_auth.get_projects()
        target_projects = target_data.get("data", []) if target_data else []
        if not target_projects:
            st.error("No projects found in target company.")
            return
        target_project = st.selectbox(
            "Select Target Project",
            [(p["id"], p["name"]) for p in target_projects],
            format_func=lambda x: x[1],
            key="copy_docs_target_project",
        )

    st.divider()
    st.subheader("Document IDs")
    st.caption("Upload an Excel file with document IDs in the first column.")
    excel_file = st.file_uploader(
        "Upload Excel (.xlsx / .xls)",
        type=["xlsx", "xls"],
        key="copy_docs_excel",
    )

    doc_ids = []
    if excel_file:
        doc_ids = _parse_doc_ids(excel_file)
        st.info(f"**{len(doc_ids)}** document ID(s) found.")
        with st.expander("Preview IDs"):
            for did in doc_ids:
                st.write(f"- `{did}`")

    if not doc_ids:
        return

    # Retry section — shown whenever there are pending external data patches
    pending = st.session_state.get("pending_external_data", [])
    if pending:
        st.warning(f"**{len(pending)}** document(s) are waiting for external data to be set.")
        st.dataframe(
            [{"Source Doc ID": p["sourceDocId"], "Main File ID": p["mainFileId"]} for p in pending],
            use_container_width=True,
        )
        if st.button("Retry Pending External Data"):
            target_auth = st.session_state["target_auth"]
            still_pending = []
            for item in pending:
                r = requests.get(
                    f"{target_auth.base_url}/documents",
                    headers=target_auth.get_headers(),
                    params={"fileId": item["mainFileId"], "limit": 5},
                )
                if r.status_code == 200:
                    docs = r.json().get("data", [])
                    if docs:
                        new_doc_id = docs[0]["id"]
                        ext = requests.post(
                            f"{target_auth.base_url}/documents/{new_doc_id}/external-data",
                            json={"groundTruthDocumentId": item["sourceDocId"]},
                            headers=target_auth.get_headers(),
                        )
                        if ext.status_code in (200, 201, 202):
                            st.success(f"✅ Patched: `{item['sourceDocId']}` → `{new_doc_id}`")
                        else:
                            st.error(f"Failed to patch `{item['sourceDocId']}`: HTTP {ext.status_code}")
                            still_pending.append(item)
                    else:
                        st.warning(f"Document still not found for fileId `{item['mainFileId']}`.")
                        still_pending.append(item)
                else:
                    st.warning(f"API error {r.status_code} for fileId `{item['mainFileId']}`.")
                    still_pending.append(item)
            st.session_state["pending_external_data"] = still_pending
            if not still_pending:
                st.success("All pending patches completed!")

    st.divider()
    if st.button("Copy Documents", type="primary"):
        results = []
        success_count = 0
        fail_count = 0

        for i, doc_id in enumerate(doc_ids, 1):
            st.markdown(f"### Document {i}/{len(doc_ids)}: `{doc_id}`")
            result = _copy_one_document(
                doc_id, source_auth, target_auth, target_project[0]
            )
            results.append(result)
            if result["status"] == "success":
                success_count += 1
            else:
                fail_count += 1
            st.divider()

        st.subheader("Summary")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total", len(results))
        col2.metric("Succeeded", success_count)
        col3.metric("Failed / Partial", fail_count)

        if results:
            st.subheader("Result Details")
            st.dataframe(
                [
                    {
                        "Source Doc ID": r.get("sourceDocId", "—"),
                        "Target Doc ID": r.get("targetDocId", "—"),
                        "Status": r["status"],
                        "Failed Step": r.get("step", "—"),
                    }
                    for r in results
                ],
                use_container_width=True,
            )


def main():
    st.title("Copy Documents")
    st.caption(
        "Downloads files from documents in the source project and re-uploads them to the target project "
        "using the File Batch Processing endpoint (POST /cases/process-file-batch) — the same endpoint "
        "used when uploading new files directly. The difference to a regular file upload is that the "
        "source files come from existing documents rather than local files. Each copied document is "
        "linked back to its original via groundTruthDocumentId."
    )

    input_credentials()
    if st.button("Authenticate Credentials"):
        _authenticate()

    if "source_auth" not in st.session_state or "target_auth" not in st.session_state:
        return

    st.divider()
    _copy_documents_section()


if __name__ == "__main__":
    main()
