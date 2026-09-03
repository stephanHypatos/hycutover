import difflib

import streamlit as st

from auth import HypatosAPI
from config import BASE_URL_EU, BASE_URL_US

st.set_page_config(page_title="Compare Composite Enrichment Workflows", layout="wide")
st.title("Compare Composite Enrichment Workflows")
st.caption(
    "Compare two composite enrichment workflow definitions side by side — across two "
    "companies or within one. The definition is a YAML document, so the core of the "
    "comparison is a line-level diff. Purpose-built for spotting prod-vs-test drift."
)


def _reset(prefix: str = "ccew_"):
    for key in list(st.session_state.keys()):
        if key.startswith(prefix):
            st.session_state.pop(key, None)


def _meta(workflow: dict) -> dict:
    definition = workflow.get("definition") or ""
    return {
        "name": workflow.get("name"),
        "description": workflow.get("description") or "",
        "version": workflow.get("versionString") or workflow.get("version"),
        "definition lines": len(definition.splitlines()),
        "updatedAt": workflow.get("updatedAt"),
        "id": workflow.get("id"),
    }


def _label(workflow: dict) -> str:
    wid = workflow.get("id") or "?"
    name = workflow.get("name") or "Unnamed"
    version = workflow.get("versionString") or workflow.get("version") or "?"
    return f"{name} · v{version} ({str(wid)[:8]}…)"


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
            st.code(text_a or "(empty)", language="yaml")
    with col_r:
        with st.expander("B · raw"):
            st.code(text_b or "(empty)", language="yaml")


col_reset_l, col_reset_r = st.columns([5, 1])
with col_reset_r:
    if st.button("Reset", key="ccew_reset"):
        _reset()
        st.rerun()


# ---------------------------------------------------------------------------
# Step 1 — Credentials
# ---------------------------------------------------------------------------
st.header("Step 1: Credentials")
st.markdown("Required scope: `enrichment-workflows.read` on both companies.")

col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Company A")
    a_env = st.selectbox(
        "Region",
        (BASE_URL_EU, BASE_URL_US),
        key="ccew_a_env",
        format_func=lambda u: "EU" if u == BASE_URL_EU else "US",
    )
    a_id = st.text_input("Company A client_id", key="ccew_a_id")
    a_secret = st.text_input("Company A client_secret", type="password", key="ccew_a_secret")

with col_b:
    st.subheader("Company B")
    same_company = st.checkbox(
        "Same as A (compare within one company)",
        key="ccew_same",
    )
    if same_company:
        st.info("Company B will reuse Company A credentials.")
        b_env, b_id, b_secret = a_env, a_id, a_secret
    else:
        b_env = st.selectbox(
            "Region",
            (BASE_URL_EU, BASE_URL_US),
            key="ccew_b_env",
            format_func=lambda u: "EU" if u == BASE_URL_EU else "US",
        )
        b_id = st.text_input("Company B client_id", key="ccew_b_id")
        b_secret = st.text_input("Company B client_secret", type="password", key="ccew_b_secret")

if not st.session_state.get("ccew_authed"):
    if st.button("Authenticate", key="ccew_auth"):
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

            st.session_state["ccew_a_api"] = a_api
            st.session_state["ccew_b_api"] = b_api
            st.session_state["ccew_a_company"] = a_company
            st.session_state["ccew_b_company"] = b_company
            st.session_state["ccew_authed"] = True
            st.rerun()
    st.stop()

a_api: HypatosAPI = st.session_state["ccew_a_api"]
b_api: HypatosAPI = st.session_state["ccew_b_api"]
a_company = st.session_state["ccew_a_company"]
b_company = st.session_state["ccew_b_company"]
same_company = a_company.get("id") == b_company.get("id")

st.success(
    f"A: **{a_company.get('name', '?')}** (`{a_company.get('id', '?')}`) · "
    f"B: **{b_company.get('name', '?')}** (`{b_company.get('id', '?')}`)"
    + ("  ·  *same company*" if same_company else "")
)


# ---------------------------------------------------------------------------
# Step 2 — Pick the two workflows
# ---------------------------------------------------------------------------
st.header("Step 2: Pick the two workflows")

if "ccew_a_workflows" not in st.session_state:
    if st.button("Load workflows", key="ccew_load"):
        with st.spinner("Fetching enrichment workflows from both companies…"):
            a_wfs = a_api.list_enrichment_workflows()
            b_wfs = a_wfs if same_company else b_api.list_enrichment_workflows()
        if not a_wfs:
            st.error(f"No enrichment workflows found for Company A. {a_api.last_error or ''}")
            st.stop()
        if not b_wfs:
            st.error(f"No enrichment workflows found for Company B. {b_api.last_error or ''}")
            st.stop()
        st.session_state["ccew_a_workflows"] = a_wfs
        st.session_state["ccew_b_workflows"] = b_wfs
        st.rerun()
    st.stop()

a_wfs = st.session_state["ccew_a_workflows"]
b_wfs = st.session_state["ccew_b_workflows"]

a_map = {_label(w): w for w in a_wfs if w.get("id")}
b_map = {_label(w): w for w in b_wfs if w.get("id")}

col_sel_a, col_sel_b = st.columns(2)
with col_sel_a:
    a_pick = st.selectbox(
        f"Workflow A — {a_company.get('name', '?')}",
        list(a_map.keys()),
        key="ccew_a_pick",
    )
with col_sel_b:
    b_pick = st.selectbox(
        f"Workflow B — {b_company.get('name', '?')}",
        list(b_map.keys()),
        key="ccew_b_pick",
    )

if st.button("Load full detail & compare", key="ccew_load_detail", type="primary"):
    with st.spinner("Fetching full workflow definitions…"):
        a_full = a_api.get_enrichment_workflow(a_map[a_pick]["id"])
        b_full = b_api.get_enrichment_workflow(b_map[b_pick]["id"])
    if a_full is None:
        st.error(f"Failed to fetch Workflow A. {a_api.last_error or ''}")
        st.stop()
    if b_full is None:
        st.error(f"Failed to fetch Workflow B. {b_api.last_error or ''}")
        st.stop()
    st.session_state["ccew_a_full"] = a_full
    st.session_state["ccew_b_full"] = b_full
    st.rerun()

if "ccew_a_full" not in st.session_state:
    st.stop()

a_full = st.session_state["ccew_a_full"]
b_full = st.session_state["ccew_b_full"]


# ---------------------------------------------------------------------------
# Step 3 — Comparison
# ---------------------------------------------------------------------------
st.header("Step 3: Comparison")

a_def = a_full.get("definition") or ""
b_def = b_full.get("definition") or ""

if (
    a_def == b_def
    and (a_full.get("name") or "") == (b_full.get("name") or "")
    and (a_full.get("description") or "") == (b_full.get("description") or "")
):
    st.success("✅ The two workflows are identical (name, description and definition).")
else:
    st.warning("❗️ The two workflows differ. See the field-by-field comparison below.")

st.caption(
    "Project bindings (`projectIds`) are **not compared** — project ids are unique to each "
    "company, so they always differ and are not meaningful for drift detection. They are "
    "omitted from the comparison entirely (still visible in each side's *Full JSON* below)."
)

meta_a, meta_b = st.columns(2)
with meta_a:
    st.subheader(f"A · {a_full.get('name', '?')}")
    st.json(_meta(a_full))
with meta_b:
    st.subheader(f"B · {b_full.get('name', '?')}")
    st.json(_meta(b_full))

_text_diff(a_full.get("name"), b_full.get("name"), "Name")
_text_diff(a_full.get("description"), b_full.get("description"), "Description")
_text_diff(a_def, b_def, "Definition (YAML)")

with st.expander("Full A JSON"):
    st.json(a_full)
with st.expander("Full B JSON"):
    st.json(b_full)
