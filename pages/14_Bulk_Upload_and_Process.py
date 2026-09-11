import time

import pandas as pd
import streamlit as st

from auth import HypatosAPI
from config import BASE_URL_EU, BASE_URL_US

st.set_page_config(page_title="Bulk Upload & Process", page_icon=":arrows_counterclockwise:")

# --- Session-state keys are prefixed bup_ (Bulk UPload) --------------------

_MIME_TYPES = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "tiff": "image/tiff",
    "tif": "image/tiff",
    "csv": "text/csv",
    "html": "text/html",
    "xml": "application/xml",
    "json": "application/json",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
_ACCEPTED_EXTENSIONS = list(_MIME_TYPES.keys())

# Document states that mean "still being worked on" by the platform.
_IN_PROGRESS_STATES = {"new", "processing"}
# States we surface as an error (everything else settled counts as done).
_FAILED_STATES = {"failed", "rejected"}


def _content_type(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return _MIME_TYPES.get(ext, "application/octet-stream")


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


# --- Authentication --------------------------------------------------------

def _authenticate():
    client_id = st.session_state.get("bup_client_id", "")
    client_secret = st.session_state.get("bup_client_secret", "")
    base_url = st.session_state.get("bup_base_url", BASE_URL_EU)

    if not client_id or not client_secret:
        st.error("Please provide credentials.")
        return

    auth = HypatosAPI(client_id, client_secret, base_url)
    if auth.authenticate():
        st.session_state["bup_auth"] = auth
        company = auth.get_company_info()
        st.session_state["bup_company_name"] = company.get("name", "Unknown") if company else "Unknown"
        st.success("Authentication succeeded!")
    else:
        st.error(f"Authentication failed: {auth.last_error or 'Unknown error'}")


# --- Status rendering ------------------------------------------------------

_STATUS_ORDER = ["pending", "uploaded", "processing", "done", "failed"]


def _counts(items) -> dict:
    counts = {s: 0 for s in _STATUS_ORDER}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    return counts


def _render_status(items, count_ph, table_ph, progress_ph):
    counts = _counts(items)
    total = len(items)
    done_like = counts["done"] + counts["failed"]

    with count_ph.container():
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Total", total)
        c2.metric("Pending", counts["pending"] + counts["uploaded"])
        c3.metric("Processing", counts["processing"])
        c4.metric("Done", counts["done"])
        c5.metric("Failed", counts["failed"])
        c6.metric("Complete", f"{(done_like / total * 100) if total else 0:.0f}%")

    progress_ph.progress(done_like / total if total else 0.0)

    rows = []
    for it in items:
        rows.append({
            "file": it["name"],
            "size": _human_size(it["size"]),
            "status": it["status"],
            "state": it.get("state") or "",
            "document id": it.get("document_id") or "",
            "error": (it.get("error") or "")[:200],
        })
    table_ph.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# --- The batch run ---------------------------------------------------------

def _run(auth, project_id, items, uploaded_by_index, batch_size, interval, timeout,
         count_ph, table_ph, progress_ph, log_ph):
    # Work on everything that is not already finished; this makes the run
    # resumable and lets failed files be retried on a later click.
    todo = [i for i, it in enumerate(items) if it["status"] != "done"]
    if not todo:
        log_ph.info("Nothing to do — every file is already done.")
        return

    for start in range(0, len(todo), batch_size):
        batch = todo[start:start + batch_size]
        batch_no = start // batch_size + 1
        total_batches = (len(todo) + batch_size - 1) // batch_size
        log_ph.info(f"Batch {batch_no}/{total_batches}: {len(batch)} file(s)")

        # 1) Upload any file that does not yet have a file id.
        for idx in batch:
            it = items[idx]
            if it.get("file_id"):
                continue
            f = uploaded_by_index[idx]
            data = f.getvalue()
            result = auth.upload_file(data, _content_type(it["name"]), it["name"])
            del data
            if result and result.get("id"):
                it["file_id"] = result["id"]
                it["status"] = "uploaded"
                it["error"] = None
            else:
                it["status"] = "failed"
                it["error"] = f"upload failed: {auth.last_error or 'unknown error'}"
            _render_status(items, count_ph, table_ph, progress_ph)

        # 2) Request processing into a document for every uploaded file.
        for idx in batch:
            it = items[idx]
            if it["status"] == "failed" or it.get("document_id"):
                continue
            if not it.get("file_id"):
                continue
            result = auth.process_file_into_document(it["file_id"], project_id)
            if result and result.get("documentId"):
                it["document_id"] = result["documentId"]
                it["status"] = "processing"
                it["state"] = "new"
                it["error"] = None
            else:
                it["status"] = "failed"
                it["error"] = f"process-file failed: {auth.last_error or 'unknown error'}"
            _render_status(items, count_ph, table_ph, progress_ph)

        # 3) Poll until every document in this batch has settled (or we time out).
        pending = {it["document_id"]: idx for idx in batch
                   for it in [items[idx]]
                   if it["status"] == "processing" and it.get("document_id")}
        deadline = time.time() + timeout
        while pending:
            if time.time() > deadline:
                log_ph.warning(
                    f"Batch {batch_no}: timed out after {timeout}s with "
                    f"{len(pending)} document(s) still processing. They keep their "
                    f"'processing' status — click Start again to keep waiting."
                )
                break
            time.sleep(interval)

            in_progress = _fetch_in_progress(auth, project_id, set(pending.keys()))

            for doc_id in list(pending.keys()):
                idx = pending[doc_id]
                it = items[idx]
                if doc_id in in_progress:
                    it["state"] = in_progress[doc_id] or it.get("state")
                    continue
                # Not in the in-progress page any more → confirm final state.
                doc = auth.get_document_by_id(doc_id)
                state = (doc or {}).get("state")
                if state in _IN_PROGRESS_STATES:
                    # Not indexed yet / transient — keep waiting.
                    it["state"] = state
                    continue
                it["state"] = state or "unknown"
                if state in _FAILED_STATES:
                    it["status"] = "failed"
                    it["error"] = f"document state: {state}"
                else:
                    it["status"] = "done"
                    it["error"] = None
                del pending[doc_id]
            _render_status(items, count_ph, table_ph, progress_ph)

    _render_status(items, count_ph, table_ph, progress_ph)
    counts = _counts(items)
    if counts["failed"]:
        log_ph.warning(
            f"Finished. {counts['done']} done, {counts['failed']} failed, "
            f"{counts['processing']} still processing. Click Start again to retry."
        )
    elif counts["processing"] or counts["pending"] or counts["uploaded"]:
        log_ph.info("Finished this pass — some files still pending/processing. Click Start again to continue.")
    else:
        log_ph.success(f"All {counts['done']} file(s) processed. 🎉")


def _fetch_in_progress(auth, project_id, wanted_ids: set) -> dict:
    """
    Return {documentId: state} for the wanted documents that are still in
    new/processing, by paging GET /documents filtered to those states. One or
    two calls per poll round regardless of batch size.
    """
    found = {}
    offset = 0
    limit = 50
    while True:
        body = auth.list_documents(
            project_id=project_id,
            states=["new", "processing"],
            limit=limit,
            offset=offset,
        )
        if not body:
            break
        batch = body.get("data", [])
        for d in batch:
            did = d.get("id")
            if did in wanted_ids:
                found[did] = d.get("state")
        if len(batch) < limit:
            break
        offset += limit
    return found


# --- Page ------------------------------------------------------------------

def main():
    st.title("Bulk Upload & Process Files")
    st.caption(
        "Upload a folder of documents and let the app upload them, request "
        "processing, and wait for each batch to finish before starting the "
        "next — so neither Streamlit nor the API is overwhelmed."
    )

    # Step 1 — credentials -------------------------------------------------
    st.header("1. Credentials")
    st.selectbox(
        "API Region",
        (BASE_URL_EU, BASE_URL_US),
        key="bup_base_url",
        format_func=lambda url: "EU - api.cloud.hypatos.ai" if url == BASE_URL_EU else "US - api.cloud.hypatos.com",
    )
    st.text_input("Client ID", key="bup_client_id")
    st.text_input("Client Secret", type="password", key="bup_client_secret")
    if st.button("Authenticate"):
        _authenticate()

    if "bup_auth" not in st.session_state:
        return
    auth = st.session_state["bup_auth"]
    st.info(f"Company: **{st.session_state.get('bup_company_name', 'Unknown')}**")

    # Step 2 — project -----------------------------------------------------
    st.divider()
    st.header("2. Target project")
    data = auth.get_projects()
    if not data or not data.get("data"):
        st.error("Failed to retrieve projects (or none exist for this company).")
        return
    project_list = [(p["id"], p["name"]) for p in data["data"]]
    selected_project = st.selectbox(
        "Documents will be processed into this project",
        project_list,
        format_func=lambda x: x[1],
        key="bup_project_select",
    )
    project_id = selected_project[0]

    # Step 3 — files -------------------------------------------------------
    st.divider()
    st.header("3. Choose files")
    uploaded = st.file_uploader(
        "Drag in a whole folder of documents (nothing is sent yet)",
        accept_multiple_files=True,
        type=_ACCEPTED_EXTENSIONS,
        key="bup_uploader",
    )
    uploaded = uploaded or []
    if uploaded:
        total_size = sum(f.size for f in uploaded)
        st.write(f"**{len(uploaded)} file(s)** selected — {_human_size(total_size)} total.")
        if total_size > 1_500_000_000:
            st.warning(
                "That's a large selection. Every selected file is held in server "
                "memory at once. If the app runs out of memory, split the folder "
                "into a couple of selections — progress is kept and resumes."
            )

    # Step 4 — batching settings ------------------------------------------
    st.divider()
    st.header("4. Batch settings")
    c1, c2, c3 = st.columns(3)
    batch_size = c1.number_input("Files per batch", min_value=1, max_value=200, value=50, step=10, key="bup_batch_size")
    interval = c2.number_input("Poll interval (s)", min_value=2, max_value=60, value=5, step=1, key="bup_interval")
    timeout = c3.number_input("Per-batch timeout (s)", min_value=30, max_value=7200, value=600, step=30, key="bup_timeout")

    # Step 5 — run ---------------------------------------------------------
    st.divider()
    st.header("5. Upload & process")

    col_start, col_reset = st.columns([3, 1])
    start = col_start.button("▶ Start processing", type="primary", disabled=not uploaded)
    if col_reset.button("Reset progress"):
        st.session_state.pop("bup_items", None)
        st.rerun()

    count_ph = st.empty()
    progress_ph = st.empty()
    log_ph = st.empty()
    table_ph = st.empty()

    # (Re)build the tracking list when the selection changes.
    existing = st.session_state.get("bup_items")
    selection_sig = [(f.name, f.size) for f in uploaded]
    if existing is None or [(i["name"], i["size"]) for i in existing] != selection_sig:
        st.session_state["bup_items"] = [
            {
                "name": f.name,
                "size": f.size,
                "status": "pending",
                "file_id": None,
                "document_id": None,
                "state": None,
                "error": None,
            }
            for f in uploaded
        ]
    items = st.session_state.get("bup_items", [])

    if items:
        _render_status(items, count_ph, table_ph, progress_ph)

    if start:
        if not uploaded:
            st.error("Select some files first.")
        else:
            _run(
                auth, project_id, items, list(uploaded),
                int(batch_size), int(interval), int(timeout),
                count_ph, table_ph, progress_ph, log_ph,
            )


if __name__ == "__main__":
    main()
