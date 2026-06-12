import time
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
from config import BASE_URL_EU, BASE_URL_US
from auth import HypatosAPI

st.set_page_config(page_title="Document Polling", page_icon=":satellite:")

_ADMIN_USER = "admin"
_ADMIN_PASSWORD = "admin123"


# ---------------------------------------------------------------------------
# Admin gate
# ---------------------------------------------------------------------------

def _check_admin() -> bool:
    if st.session_state.get("polling_admin_ok"):
        col1, col2 = st.columns([5, 1])
        with col2:
            if st.button("Logout", key="polling_logout"):
                st.session_state["polling_admin_ok"] = False
                st.rerun()
        return True

    st.subheader("Admin Login")
    st.caption("This page is restricted to admin users.")
    username = st.text_input("Username", key="polling_admin_user")
    password = st.text_input("Password", type="password", key="polling_admin_pw")

    if st.button("Login", key="polling_admin_login"):
        if username == _ADMIN_USER and password == _ADMIN_PASSWORD:
            st.session_state["polling_admin_ok"] = True
            st.rerun()
        else:
            st.error("Invalid credentials.")

    return False


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _fetch_documents(auth: HypatosAPI, project_id: str) -> tuple[dict | None, int]:
    try:
        r = requests.get(
            f"{auth.base_url}/documents",
            headers=auth.get_headers(),
            params={"projectId": project_id, "limit": 50},
            timeout=30,
        )
        if r.status_code == 200:
            return r.json(), r.status_code
        return None, r.status_code
    except requests.Timeout:
        return None, 504
    except requests.RequestException:
        return None, 0


def _docs_to_df(data: dict) -> pd.DataFrame:
    docs = data.get("data", [])
    if not docs:
        return pd.DataFrame()
    return pd.DataFrame([
        {
            "Document ID": d.get("id", ""),
            "File ID":     d.get("fileId", ""),
            "Title":       d.get("title", ""),
            "State":       d.get("state", ""),
            "Created At":  d.get("createdAt", ""),
            "Case ID":     d.get("caseId", ""),
        }
        for d in docs
    ])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.title("Document Polling")

    if not _check_admin():
        return

    st.divider()

    # --- Config inputs ---
    st.subheader("Configuration")

    col_region, col_interval = st.columns(2)
    with col_region:
        base_url = st.selectbox(
            "API Region",
            (BASE_URL_EU, BASE_URL_US),
            format_func=lambda u: "EU — api.cloud.hypatos.ai" if u == BASE_URL_EU else "US — api.cloud.hypatos.com",
            key="poll_base_url",
        )
    with col_interval:
        interval = st.number_input(
            "Poll Interval (seconds)",
            min_value=10,
            max_value=300,
            value=30,
            step=5,
            key="poll_interval",
        )

    col_id, col_secret = st.columns(2)
    with col_id:
        client_id = st.text_input("Client ID", key="poll_client_id")
    with col_secret:
        client_secret = st.text_input("Client Secret", type="password", key="poll_client_secret")

    project_id = st.text_input("Project ID", key="poll_project_id")

    if st.button("Authenticate", key="poll_auth_btn"):
        if not client_id or not client_secret or not project_id:
            st.error("Please fill in all fields.")
        else:
            auth = HypatosAPI(client_id, client_secret, base_url)
            if auth.authenticate():
                st.session_state["poll_auth"] = auth
                st.success("Authentication succeeded!")
            else:
                st.error(f"Authentication failed: {auth.last_error or 'Unknown error'}")
                st.session_state.pop("poll_auth", None)

    if "poll_auth" not in st.session_state:
        return

    st.divider()

    # --- Polling controls ---
    polling_active = st.session_state.get("polling_active", False)

    col_start, col_stop = st.columns(2)
    with col_start:
        if st.button("▶ Start Polling", disabled=polling_active, type="primary"):
            st.session_state["polling_active"] = True
            st.session_state["poll_count"] = 0
            st.session_state["poll_last_df"] = pd.DataFrame()
            st.session_state["poll_last_time"] = None
            st.session_state["poll_total_count"] = 0
            st.rerun()
    with col_stop:
        if st.button("⏹ Stop Polling", disabled=not polling_active):
            st.session_state["polling_active"] = False
            st.rerun()

    # --- Polling loop ---
    if st.session_state.get("polling_active"):
        auth = st.session_state["poll_auth"]
        pid  = st.session_state.get("poll_project_id", project_id)

        with st.spinner(f"Fetching documents for project `{pid}`…"):
            data, status_code = _fetch_documents(auth, pid)

        now = datetime.now().strftime("%H:%M:%S")

        if data is None:
            st.session_state["poll_last_status"] = status_code
            st.error(f"Request failed (HTTP {status_code}). Check credentials / project ID.")
            st.session_state["polling_active"] = False
        else:
            df = _docs_to_df(data)
            total_count = data.get("totalCount", len(df))

            st.session_state["poll_count"]       = st.session_state.get("poll_count", 0) + 1
            st.session_state["poll_last_df"]     = df
            st.session_state["poll_last_time"]   = now
            st.session_state["poll_total_count"] = total_count
            st.session_state["poll_last_status"] = status_code

        # Status bar
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Poll #",          st.session_state.get("poll_count", 0))
        c2.metric("Last Poll",       st.session_state.get("poll_last_time", "—"))
        c3.metric("Total Documents", st.session_state.get("poll_total_count", 0))
        c4.metric("HTTP Status",     st.session_state.get("poll_last_status", "—"))

        last_df = st.session_state.get("poll_last_df", pd.DataFrame())
        if not last_df.empty:
            st.caption(f"Showing {len(last_df)} of {st.session_state.get('poll_total_count', 0)} documents (limit 50)")
            st.dataframe(last_df, use_container_width=True)
        else:
            st.info("No documents found for this project.")

        st.caption(f"Next poll in {interval}s — click **Stop Polling** to cancel.")
        time.sleep(interval)
        st.rerun()

    elif st.session_state.get("poll_last_df") is not None:
        # Show last results after polling stopped
        last_df = st.session_state.get("poll_last_df", pd.DataFrame())
        if not last_df.empty:
            st.subheader("Last Poll Results")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Polls",      st.session_state.get("poll_count", 0))
            c2.metric("Last Poll At",     st.session_state.get("poll_last_time", "—"))
            c3.metric("Total Documents",  st.session_state.get("poll_total_count", 0))
            c4.metric("Last HTTP Status", st.session_state.get("poll_last_status", "—"))
            st.caption(f"Showing {len(last_df)} of {st.session_state.get('poll_total_count', 0)} documents")
            st.dataframe(last_df, use_container_width=True)


if __name__ == "__main__":
    main()
