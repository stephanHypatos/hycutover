import streamlit as st
from auth import HypatosAPI
from config import BASE_URL_EU, BASE_URL_US

st.set_page_config(page_title="File Batch Processing", page_icon=":inbox_tray:")

_MIME_TYPES = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "tiff": "image/tiff",
    "tif": "image/tiff",
    "xml": "application/xml",
}
_ACCEPTED_EXTENSIONS = list(_MIME_TYPES.keys())


def _authenticate():
    client_id = st.session_state.get("batch_client_id", "")
    client_secret = st.session_state.get("batch_client_secret", "")
    base_url = st.session_state.get("batch_base_url", BASE_URL_EU)

    if not client_id or not client_secret:
        st.error("Please provide credentials.")
        return

    auth = HypatosAPI(client_id, client_secret, base_url)
    if auth.authenticate():
        st.session_state["batch_auth"] = auth
        company = auth.get_company_info()
        if company:
            st.session_state["batch_company_name"] = company.get("name", "Unknown")
        st.success("Authentication succeeded!")
        if st.session_state.get("batch_company_name"):
            st.info(f"Company: **{st.session_state['batch_company_name']}**")
    else:
        error_msg = auth.last_error or "Unknown error"
        st.error(f"Authentication failed: {error_msg}")


def _upload_section():
    st.header("Upload Files")
    auth = st.session_state["batch_auth"]

    uploaded_files = st.file_uploader(
        "Drag and drop files here",
        accept_multiple_files=True,
        type=_ACCEPTED_EXTENSIONS,
        key="batch_file_uploader",
    )

    if uploaded_files:
        if st.button("Upload Files"):
            if "uploaded_file_ids" not in st.session_state:
                st.session_state["uploaded_file_ids"] = []

            for f in uploaded_files:
                ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
                content_type = _MIME_TYPES.get(ext, "application/octet-stream")
                result = auth.upload_file(f.read(), content_type, f.name)
                if result and result.get("id"):
                    st.session_state["uploaded_file_ids"].append({"name": f.name, "id": result["id"]})
                    st.success(f"✅ {f.name} → `{result['id']}`")
                else:
                    err = auth.last_error or "Unknown error"
                    st.error(f"❌ Failed to upload **{f.name}**: {err}")

    if st.session_state.get("uploaded_file_ids"):
        st.subheader(f"Uploaded this session ({len(st.session_state['uploaded_file_ids'])} files)")
        for entry in st.session_state["uploaded_file_ids"]:
            st.write(f"- **{entry['name']}**: `{entry['id']}`")
        if st.button("Clear Uploaded Files"):
            st.session_state["uploaded_file_ids"] = []
            st.rerun()


def _process_batch_section():
    st.header("Process Batch")
    auth = st.session_state["batch_auth"]

    if not st.session_state.get("uploaded_file_ids"):
        st.info("Upload files above before processing.")
        return

    data = auth.get_projects()
    if not data:
        st.error("Failed to retrieve projects.")
        return
    projects = data.get("data", [])
    if not projects:
        st.info("No projects found for this company.")
        return

    project_list = [(p["id"], p["name"]) for p in projects]
    selected_project = st.selectbox(
        "Select Project",
        project_list,
        format_func=lambda x: x[1],
        key="batch_project_select",
    )

    file_ids = [e["id"] for e in st.session_state["uploaded_file_ids"]]
    st.write(f"**{len(file_ids)} file(s)** will be submitted:")
    for entry in st.session_state["uploaded_file_ids"]:
        st.write(f"- {entry['name']}: `{entry['id']}`")

    if st.button("Process Batch"):
        result = auth.process_file_batch(file_ids, selected_project[0])
        if result is not None:
            st.success("Batch processing initiated successfully!")
            st.json(result)
        else:
            err = auth.last_error or "Unknown error"
            st.error(f"Failed to process batch: {err}")


def main():
    st.title("File Batch Processing")

    st.header("Credentials")
    st.selectbox(
        "API Region",
        (BASE_URL_EU, BASE_URL_US),
        key="batch_base_url",
        format_func=lambda url: "EU - api.cloud.hypatos.ai" if url == BASE_URL_EU else "US - api.cloud.hypatos.com",
    )
    st.text_input("Client ID", key="batch_client_id")
    st.text_input("Client Secret", type="password", key="batch_client_secret")

    if st.button("Authenticate"):
        _authenticate()

    if "batch_auth" not in st.session_state:
        return

    st.divider()
    _upload_section()
    st.divider()
    _process_batch_section()


if __name__ == "__main__":
    main()
