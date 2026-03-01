import streamlit as st
from auth import HypatosAPI
from setup_api import SetupAPI
from helpers import check_admin_access
from config import BASE_URL_EU, BASE_URL_US

st.set_page_config(page_title="Copy Agent Workflow", layout="wide")
st.title("Copy Agent Workflow")

if not check_admin_access():
    st.stop()

SETUP_URL = "https://setup.cloud.hypatos.ai"

# ---------------------------------------------------------------------------
# Step 1 – Source company credentials
# ---------------------------------------------------------------------------
st.header("Step 1: Source Company Credentials")

if "caw_source_company" not in st.session_state:
    env = st.selectbox("Environment", [BASE_URL_EU, BASE_URL_US], key="caw_source_env")
    src_id = st.text_input("Source client_id", key="caw_src_id")
    src_secret = st.text_input("Source client_secret", type="password", key="caw_src_secret")

    if st.button("Authenticate Source", key="caw_auth_source"):
        if src_id.strip() and src_secret.strip():
            api = HypatosAPI(src_id.strip(), src_secret.strip(), env)
            if api.authenticate():
                company = api.get_company()
                if company:
                    st.session_state["caw_source_auth"] = api
                    st.session_state["caw_source_company"] = company
                    st.rerun()
                else:
                    st.error(f"Authenticated but could not fetch company. {api.last_error or ''}")
            else:
                st.error(f"Authentication failed. {api.last_error or ''}")
        else:
            st.error("Please fill in both client_id and client_secret.")
    st.stop()

src = st.session_state["caw_source_company"]
st.success(f"Source: **{src.get('name', src.get('id', 'Unknown'))}** (ID: `{src.get('id', '?')}`)")

# ---------------------------------------------------------------------------
# Step 2 – Target company credentials
# ---------------------------------------------------------------------------
st.header("Step 2: Target Company Credentials")

if "caw_target_company" not in st.session_state:
    env2 = st.selectbox("Environment", [BASE_URL_EU, BASE_URL_US], key="caw_target_env")
    tgt_id = st.text_input("Target client_id", key="caw_tgt_id")
    tgt_secret = st.text_input("Target client_secret", type="password", key="caw_tgt_secret")

    if st.button("Authenticate Target", key="caw_auth_target"):
        if tgt_id.strip() and tgt_secret.strip():
            api = HypatosAPI(tgt_id.strip(), tgt_secret.strip(), env2)
            if api.authenticate():
                company = api.get_company()
                if company:
                    st.session_state["caw_target_auth"] = api
                    st.session_state["caw_target_company"] = company
                    st.rerun()
                else:
                    st.error(f"Authenticated but could not fetch company. {api.last_error or ''}")
            else:
                st.error(f"Authentication failed. {api.last_error or ''}")
        else:
            st.error("Please fill in both client_id and client_secret.")
    st.stop()

tgt = st.session_state["caw_target_company"]
st.success(f"Target: **{tgt.get('name', tgt.get('id', 'Unknown'))}** (ID: `{tgt.get('id', '?')}`)")

# ---------------------------------------------------------------------------
# Step 3 – Setup access token
# ---------------------------------------------------------------------------
st.header("Step 3: Setup Access Token")

if "caw_setup_token" not in st.session_state:
    st.info(
        "Paste your `access_token` cookie from an active "
        f"[{SETUP_URL}]({SETUP_URL}) browser session."
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
        key="caw_token_input",
    )

    if st.button("Verify token", key="caw_verify_token"):
        if token_input.strip():
            setup_api = SetupAPI(token_input.strip())
            source_company_id = st.session_state["caw_source_company"].get("id")
            with st.spinner("Verifying token against source company prompting settings…"):
                result = setup_api.get_prompting_settings(source_company_id)
            if result is not None:
                st.session_state["caw_setup_token"] = token_input.strip()
                st.rerun()
            else:
                st.error(f"Token verification failed. {setup_api.last_error or 'No data returned.'}")
        else:
            st.error("Please paste a valid token before verifying.")
    st.stop()

col1, col2 = st.columns([5, 1])
with col1:
    st.success("Setup access token verified.")
with col2:
    if st.button("Reset", key="caw_reset"):
        for key in [
            "caw_source_auth", "caw_source_company",
            "caw_target_auth", "caw_target_company",
            "caw_setup_token",
        ]:
            st.session_state.pop(key, None)
        st.rerun()

# ---------------------------------------------------------------------------
# Step 4 – Copy agent workflow (coming next)
# ---------------------------------------------------------------------------
st.header("Step 4: Copy Agent Workflow")
st.info("Implementation coming soon.")
