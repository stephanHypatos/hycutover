import difflib
import streamlit as st

from auth import HypatosAPI
from config import BASE_URL_EU, BASE_URL_US

st.set_page_config(page_title="Compare Agents", layout="wide")
st.title("Compare Agents")
st.caption(
    "Pick one agent from each company (or two from the same company) and diff "
    "their prompt, system prompt, response schema, and configuration."
)


def _reset(prefix: str = "cmp_"):
    for k in list(st.session_state.keys()):
        if k.startswith(prefix):
            st.session_state.pop(k, None)


col_reset_l, col_reset_r = st.columns([5, 1])
with col_reset_r:
    if st.button("Reset", key="cmp_reset"):
        _reset()
        st.rerun()


# ---------------------------------------------------------------------------
# Step 1 — Credentials
# ---------------------------------------------------------------------------
st.header("Step 1: Credentials")

col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Company A")
    a_env = st.selectbox(
        "Region",
        (BASE_URL_EU, BASE_URL_US),
        key="cmp_a_env",
        format_func=lambda u: "EU" if u == BASE_URL_EU else "US",
    )
    a_id = st.text_input("Company A client_id", key="cmp_a_id")
    a_secret = st.text_input("Company A client_secret", type="password", key="cmp_a_secret")

with col_b:
    st.subheader("Company B")
    same_company = st.checkbox(
        "Same as A (compare within one company)",
        key="cmp_same",
    )
    if same_company:
        st.info("Company B will reuse Company A credentials.")
        b_env, b_id, b_secret = a_env, a_id, a_secret
    else:
        b_env = st.selectbox(
            "Region",
            (BASE_URL_EU, BASE_URL_US),
            key="cmp_b_env",
            format_func=lambda u: "EU" if u == BASE_URL_EU else "US",
        )
        b_id = st.text_input("Company B client_id", key="cmp_b_id")
        b_secret = st.text_input("Company B client_secret", type="password", key="cmp_b_secret")

if not st.session_state.get("cmp_authed"):
    if st.button("Authenticate", key="cmp_auth"):
        if not (a_id and a_secret and b_id and b_secret):
            st.error("Please provide client_id and client_secret for both companies.")
        else:
            a_api = HypatosAPI(a_id.strip(), a_secret.strip(), a_env)
            if not a_api.authenticate():
                st.error(f"Company A authentication failed. {a_api.last_error or ''}")
                st.stop()
            a_company = a_api.get_company()
            if not a_company:
                st.error(f"Company A authenticated but could not fetch company. {a_api.last_error or ''}")
                st.stop()

            if same_company:
                b_api = a_api
                b_company = a_company
            else:
                b_api = HypatosAPI(b_id.strip(), b_secret.strip(), b_env)
                if not b_api.authenticate():
                    st.error(f"Company B authentication failed. {b_api.last_error or ''}")
                    st.stop()
                b_company = b_api.get_company()
                if not b_company:
                    st.error(f"Company B authenticated but could not fetch company. {b_api.last_error or ''}")
                    st.stop()

            st.session_state["cmp_a_api"] = a_api
            st.session_state["cmp_b_api"] = b_api
            st.session_state["cmp_a_company"] = a_company
            st.session_state["cmp_b_company"] = b_company
            st.session_state["cmp_authed"] = True
            st.rerun()
    st.stop()

a_api: HypatosAPI = st.session_state["cmp_a_api"]
b_api: HypatosAPI = st.session_state["cmp_b_api"]
a_company = st.session_state["cmp_a_company"]
b_company = st.session_state["cmp_b_company"]
same_company = a_company.get("id") == b_company.get("id")

st.success(
    f"A: **{a_company.get('name', '?')}** (`{a_company.get('id', '?')}`) · "
    f"B: **{b_company.get('name', '?')}** (`{b_company.get('id', '?')}`)"
    + ("  ·  *same company*" if same_company else "")
)


# ---------------------------------------------------------------------------
# Step 2 — Select agents
# ---------------------------------------------------------------------------
st.header("Step 2: Pick the two agents to compare")

if "cmp_a_agents" not in st.session_state:
    if st.button("Load agents", key="cmp_load_agents"):
        with st.spinner("Fetching agents from both companies…"):
            a_agents = a_api.list_agents()
            b_agents = a_agents if same_company else b_api.list_agents()
        if not a_agents:
            st.error(f"No agents found for Company A. {a_api.last_error or ''}")
            st.stop()
        if not b_agents:
            st.error(f"No agents found for Company B. {b_api.last_error or ''}")
            st.stop()
        st.session_state["cmp_a_agents"] = a_agents
        st.session_state["cmp_b_agents"] = b_agents
        st.rerun()
    st.stop()

a_agents = st.session_state["cmp_a_agents"]
b_agents = st.session_state["cmp_b_agents"]


def _label(a: dict) -> str:
    aid = a.get("id") or "?"
    return f"{a.get('name', 'Unnamed')} · v{a.get('version', '?')} ({aid[:8]}…)"


a_map = {_label(a): a for a in a_agents if a.get("id")}
b_map = {_label(a): a for a in b_agents if a.get("id")}

col_sel_a, col_sel_b = st.columns(2)
with col_sel_a:
    a_pick = st.selectbox(
        f"Agent A — {a_company.get('name', '?')}",
        list(a_map.keys()),
        key="cmp_a_pick",
    )
with col_sel_b:
    b_pick = st.selectbox(
        f"Agent B — {b_company.get('name', '?')}",
        list(b_map.keys()),
        key="cmp_b_pick",
    )

if st.button("Load full detail & compare", key="cmp_load_detail", type="primary"):
    with st.spinner("Fetching agent detail (with full prompt)…"):
        a_full = a_api.get_agent(a_map[a_pick]["id"])
        b_full = b_api.get_agent(b_map[b_pick]["id"])
    if a_full is None:
        st.error(f"Failed to fetch Agent A. {a_api.last_error or ''}")
        st.stop()
    if b_full is None:
        st.error(f"Failed to fetch Agent B. {b_api.last_error or ''}")
        st.stop()
    st.session_state["cmp_a_full"] = a_full
    st.session_state["cmp_b_full"] = b_full
    st.rerun()

if "cmp_a_full" not in st.session_state:
    st.stop()

a_full = st.session_state["cmp_a_full"]
b_full = st.session_state["cmp_b_full"]


# ---------------------------------------------------------------------------
# Step 3 — Comparison
# ---------------------------------------------------------------------------
st.header("Step 3: Comparison")


def _meta(x: dict) -> dict:
    return {
        "id": x.get("id"),
        "name": x.get("name"),
        "version": x.get("version"),
        "type": x.get("type"),
        "model": x.get("model"),
        "description": x.get("description"),
        "isOotb": x.get("isOotb"),
        "editors": x.get("editors"),
        "toolIds": x.get("toolIds"),
    }


meta_a, meta_b = st.columns(2)
with meta_a:
    st.subheader(f"A · {a_full.get('name', '?')}")
    st.json(_meta(a_full))
with meta_b:
    st.subheader(f"B · {b_full.get('name', '?')}")
    st.json(_meta(b_full))


def _text_diff(text_a: str, text_b: str, label: str):
    st.markdown(f"### {label}")
    text_a = text_a or ""
    text_b = text_b or ""
    if text_a == text_b:
        st.success("Identical")
    else:
        diff = list(
            difflib.unified_diff(
                text_a.splitlines(),
                text_b.splitlines(),
                fromfile="A",
                tofile="B",
                lineterm="",
                n=3,
            )
        )
        if diff:
            st.code("\n".join(diff), language="diff")
        else:
            st.info("No line-level differences (whitespace or ordering only).")
    col_l, col_r = st.columns(2)
    with col_l:
        with st.expander("A · raw"):
            st.code(text_a or "(empty)", language="text")
    with col_r:
        with st.expander("B · raw"):
            st.code(text_b or "(empty)", language="text")


_text_diff(a_full.get("prompt"), b_full.get("prompt"), "Prompt")
_text_diff(a_full.get("systemPrompt"), b_full.get("systemPrompt"), "System prompt")


def _json_diff(obj_a, obj_b, label: str):
    st.markdown(f"### {label}")
    if obj_a == obj_b:
        st.success("Identical")
    else:
        st.warning("Different")
    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**A**")
        st.json(obj_a)
    with col_r:
        st.markdown("**B**")
        st.json(obj_b)


_json_diff(a_full.get("outputFormat"), b_full.get("outputFormat"), "Response object (outputFormat)")
_json_diff(a_full.get("configuration"), b_full.get("configuration"), "Configuration")


with st.expander("Full A JSON"):
    st.json(a_full)
with st.expander("Full B JSON"):
    st.json(b_full)
