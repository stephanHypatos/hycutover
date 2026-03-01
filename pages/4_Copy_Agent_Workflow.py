import streamlit as st
from helpers import check_admin_access
from setup_api import SetupAPI

st.set_page_config(page_title="Copy Agent Workflow", layout="wide")
st.title("Copy Agent Workflow")

if not check_admin_access():
    st.stop()

# ---------------------------------------------------------------------------
# Step 1 – Setup access token
# ---------------------------------------------------------------------------
st.header("Step 1: Setup Access Token")

SETUP_URL = "https://setup.cloud.hypatos.ai"

if "setup_access_token" not in st.session_state:
    st.info(
        "This page uses the Hypatos **Setup UI** API. "
        "To authenticate, paste your `access_token` cookie from an active "
        f"[setup.cloud.hypatos.ai]({SETUP_URL}) browser session."
    )
    with st.expander("How to get your access_token", expanded=True):
        st.markdown(
            f"""
1. Open **[{SETUP_URL}]({SETUP_URL})** in your browser and log in.
2. Open **DevTools** (`F12` or right-click → *Inspect*).
3. Go to **Application** → **Cookies** → `{SETUP_URL}`.
4. Find the cookie named **`access_token`** and copy its value.
5. Paste it into the field below.
"""
        )

    token_input = st.text_input(
        "access_token",
        type="password",
        placeholder="Paste your access_token here",
        key="token_input_field",
    )
    if st.button("Save token", key="save_token"):
        if token_input.strip():
            st.session_state["setup_access_token"] = token_input.strip()
            st.rerun()
        else:
            st.error("Please paste a valid token before saving.")
    st.stop()

# Token is present – show a success badge and allow clearing it
col1, col2 = st.columns([5, 1])
with col1:
    st.success("Access token loaded.")
with col2:
    if st.button("Clear token", key="clear_token"):
        for key in ["setup_access_token", "setup_source_company", "setup_target_company"]:
            st.session_state.pop(key, None)
        st.rerun()

api = SetupAPI(st.session_state["setup_access_token"])

# ---------------------------------------------------------------------------
# Step 2 – Select source and target companies
# ---------------------------------------------------------------------------
st.header("Step 2: Select Companies")

if st.button("Load companies", key="load_companies"):
    with st.spinner("Fetching company…"):
        company = api.get_company()
    if company:
        st.session_state["setup_source_company"] = company
        st.session_state["setup_target_company"] = company
    else:
        st.error(f"Could not fetch company. {api.last_error or ''}")

if "setup_source_company" not in st.session_state:
    st.info("Click **Load companies** to verify your token and retrieve your company.")
    st.stop()

company = st.session_state["setup_source_company"]
st.success(f"Company: **{company.get('name', company.get('id', 'Unknown'))}** (ID: `{company.get('id', '?')}`)")

# ---------------------------------------------------------------------------
# Step 3 – Copy agent workflow (coming next)
# ---------------------------------------------------------------------------
st.header("Step 3: Copy Agent Workflow")
st.info("Implementation coming soon.")
