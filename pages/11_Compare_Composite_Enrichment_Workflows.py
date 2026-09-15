import difflib
import re

import streamlit as st
import yaml

from auth import HypatosAPI
from config import BASE_URL_EU, BASE_URL_US

# The composite enrichment YAML definition contains a "duplicate projects"
# section listing project ids. Project ids are unique per company, so that
# section always differs across two companies and is not meaningful for drift
# detection. We parse the YAML and structurally drop the section before diffing.
_DEFAULT_EXCLUDED_SECTIONS = "duplicate projects"

# Fields under which a step/section carries its human name in the definition.
_NAME_FIELDS = ("name", "title", "step", "type", "id", "key", "label")


def _norm_key(value) -> str:
    """Normalise a key / name for tolerant matching: lower-case and strip every
    non-alphanumeric char, so 'Duplicate Projects', 'duplicate_projects' and
    'duplicateProjects' all collapse to the same token."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _parse_targets(raw: str) -> set:
    return {_norm_key(part) for part in (raw or "").split(",") if part.strip()}


def _matches_section(node, targets: set) -> bool:
    """True if a list item (a dict) is the section to exclude, matched by any of
    its name-ish fields."""
    if isinstance(node, dict):
        for field in _NAME_FIELDS:
            if field in node and _norm_key(node[field]) in targets:
                return True
    return False


def _redact(node, targets: set, removed: list):
    """Return a copy of the parsed YAML with any matching section removed —
    both mapping keys named like the section and list items whose name matches.
    Collects the removed sub-trees into `removed` for display."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if _norm_key(key) in targets:
                removed.append({key: value})
                continue
            out[key] = _redact(value, targets, removed)
        return out
    if isinstance(node, list):
        out = []
        for item in node:
            if _matches_section(item, targets):
                removed.append(item)
                continue
            out.append(_redact(item, targets, removed))
        return out
    return node


def _canonical_definition(text: str, targets: set):
    """Parse a YAML definition, drop the excluded section(s), and re-serialise
    canonically so both sides are formatted identically for the diff.

    Returns (display_text, parsed_ok, removed_list). On a parse failure the raw
    text is returned unchanged with parsed_ok=False so the caller can fall back
    to a plain text diff."""
    text = text or ""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return text, False, []
    if data is None:
        return text, True, []
    removed: list = []
    data = _redact(data, targets, removed)
    dumped = yaml.safe_dump(
        data,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=1000,
    )
    return dumped, True, removed

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

a_def_raw = a_full.get("definition") or ""
b_def_raw = b_full.get("definition") or ""

exclude_section = st.checkbox(
    "Exclude the “duplicate projects” section from the definition diff",
    value=True,
    key="ccew_exclude",
    help=(
        "The YAML definition holds a section listing project ids for duplication. "
        "Project ids are unique per company, so this section always differs across "
        "two companies and is not real drift. With this on, the section is parsed "
        "out of both definitions before diffing."
    ),
)
section_input = st.text_input(
    "Section name(s) to exclude (comma-separated)",
    value=_DEFAULT_EXCLUDED_SECTIONS,
    key="ccew_section_names",
    disabled=not exclude_section,
    help=(
        "Matched case-insensitively and ignoring spaces / underscores / hyphens, "
        "against both mapping keys and a step's name/title. Adjust if your "
        "definition labels the section differently."
    ),
)
targets = _parse_targets(section_input) if exclude_section else set()

# Prepare the definition text used for the verdict and the diff. When excluding,
# both sides are parsed, the section dropped, and re-serialised identically so
# only meaningful content differences remain. If either side is not valid YAML,
# fall back to the raw text diff (nothing excluded).
normalised = False
removed_a: list = []
removed_b: list = []
if exclude_section and targets:
    a_disp, a_ok, removed_a = _canonical_definition(a_def_raw, targets)
    b_disp, b_ok, removed_b = _canonical_definition(b_def_raw, targets)
    if a_ok and b_ok:
        normalised = True
    else:
        a_disp, b_disp = a_def_raw, b_def_raw
        st.warning(
            "One or both definitions are not valid YAML, so the section could not "
            "be excluded — showing the raw definition diff instead."
        )
else:
    a_disp, b_disp = a_def_raw, b_def_raw

if (
    a_disp == b_disp
    and (a_full.get("name") or "") == (b_full.get("name") or "")
    and (a_full.get("description") or "") == (b_full.get("description") or "")
):
    st.success(
        "✅ The two workflows are identical (name, description and definition"
        + (", excluding the duplicate-projects section)." if normalised else ").")
    )
else:
    st.warning("❗️ The two workflows differ. See the field-by-field comparison below.")

st.caption(
    "Project bindings (`projectIds`) are **not compared** — project ids are unique to each "
    "company, so they always differ and are not meaningful for drift detection. They are "
    "omitted from the comparison entirely (still visible in each side's *Full JSON* below)."
)

if normalised:
    if removed_a or removed_b:
        st.caption(
            f"Excluded the **{section_input.strip()}** section before diffing "
            f"(removed {len(removed_a)} from A, {len(removed_b)} from B). The "
            "definition below is re-serialised YAML, so comments and exact "
            "formatting are normalised, not compared."
        )
        with st.expander("What was excluded"):
            col_x, col_y = st.columns(2)
            with col_x:
                st.markdown("**A**")
                st.code(
                    yaml.safe_dump(removed_a, sort_keys=False, allow_unicode=True)
                    if removed_a
                    else "(nothing matched)",
                    language="yaml",
                )
            with col_y:
                st.markdown("**B**")
                st.code(
                    yaml.safe_dump(removed_b, sort_keys=False, allow_unicode=True)
                    if removed_b
                    else "(nothing matched)",
                    language="yaml",
                )
    else:
        st.caption(
            f"No **{section_input.strip()}** section was found in either definition — "
            "nothing was excluded. The definition below is re-serialised YAML "
            "(comments and exact formatting normalised)."
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
_text_diff(
    a_disp,
    b_disp,
    "Definition (YAML, duplicate-projects excluded)" if normalised else "Definition (YAML)",
)

with st.expander("Full A JSON"):
    st.json(a_full)
with st.expander("Full B JSON"):
    st.json(b_full)
