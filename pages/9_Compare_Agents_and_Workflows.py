import difflib
import json
import re

import pandas as pd
import streamlit as st

from auth import HypatosAPI
from config import BASE_URL_EU, BASE_URL_US

st.set_page_config(page_title="Compare Agents & Workflows", layout="wide")
st.title("Compare Agents & Workflows")
st.caption(
    "Compare two agents, or two agent workflows plus every agent they reference. "
    "Useful for spotting drift between prod and test environments."
)


UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
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
# Shared diff helpers
# ---------------------------------------------------------------------------
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


def _agent_meta(x: dict) -> dict:
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


def _workflow_meta(x: dict) -> dict:
    return {
        "id": x.get("id"),
        "name": x.get("name"),
        "version": x.get("version"),
        "model": x.get("model"),
        "workflowType": x.get("workflowType"),
        "description": x.get("description"),
        "projects": x.get("projects"),
        "trainingCompanyId": x.get("trainingCompanyId"),
        "trainingProjects": x.get("trainingProjects"),
        "similarityThreshold": x.get("similarityThreshold"),
        "useOcrTextPages": x.get("useOcrTextPages"),
        "useImages": x.get("useImages"),
        "similarityApi": x.get("similarityApi"),
        "maxNumTrainingDocuments": x.get("maxNumTrainingDocuments"),
        "bboxRegionDetectionMode": x.get("bboxRegionDetectionMode"),
        "isOotb": x.get("isOotb"),
    }


def _find_uuids(node) -> set:
    found = set()
    if isinstance(node, dict):
        for v in node.values():
            found |= _find_uuids(v)
    elif isinstance(node, list):
        for v in node:
            found |= _find_uuids(v)
    elif isinstance(node, str):
        for m in UUID_RE.findall(node):
            found.add(m)
    return found


def _resolve_referenced_agents(wf_detail: dict, agents: list) -> list:
    """Return the agents referenced by wf_detail.workflowConfiguration.
    Matches on both UUID and name:version / quoted-name substrings against
    the given agent list (the source-side summary list is enough)."""
    wf_config = wf_detail.get("workflowConfiguration") or {}
    referenced_uuids = _find_uuids(wf_config)
    by_id = {a.get("id"): a for a in agents if a.get("id")}
    hits = [by_id[u] for u in referenced_uuids if u in by_id]

    config_str = json.dumps(wf_config)
    seen = {a.get("id") for a in hits}
    for a in agents:
        if a.get("id") in seen:
            continue
        name = (a.get("name") or "").strip()
        version = (a.get("version") or "").strip()
        if not name:
            continue
        needles = []
        if version:
            needles.append(f"{name}:{version}")
        needles.append(f'"{name}"')
        if any(n in config_str for n in needles):
            hits.append(a)
            seen.add(a.get("id"))
    return hits


# ---------------------------------------------------------------------------
# Step 2 — Mode
# ---------------------------------------------------------------------------
st.header("Step 2: What do you want to compare?")

mode = st.radio(
    "Mode",
    ["Two agents", "Two workflows (with all referenced agents)"],
    horizontal=True,
    key="cmp_mode",
)


# ===========================================================================
# Mode A — Two agents
# ===========================================================================
if mode == "Two agents":
    st.subheader("Pick the two agents")

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

    st.header("Step 3: Comparison")

    meta_a, meta_b = st.columns(2)
    with meta_a:
        st.subheader(f"A · {a_full.get('name', '?')}")
        st.json(_agent_meta(a_full))
    with meta_b:
        st.subheader(f"B · {b_full.get('name', '?')}")
        st.json(_agent_meta(b_full))

    _text_diff(a_full.get("prompt"), b_full.get("prompt"), "Prompt")
    _text_diff(a_full.get("systemPrompt"), b_full.get("systemPrompt"), "System prompt")
    _json_diff(a_full.get("outputFormat"), b_full.get("outputFormat"), "Response object (outputFormat)")
    _json_diff(a_full.get("configuration"), b_full.get("configuration"), "Configuration")

    with st.expander("Full A JSON"):
        st.json(a_full)
    with st.expander("Full B JSON"):
        st.json(b_full)


# ===========================================================================
# Mode B — Two workflows + their agents
# ===========================================================================
else:
    st.subheader("Pick the two workflows")

    if "cmp_a_workflows" not in st.session_state:
        if st.button("Load workflows", key="cmp_load_wfs"):
            with st.spinner("Fetching workflows from both companies…"):
                a_wfs = a_api.list_agent_workflows()
                b_wfs = a_wfs if same_company else b_api.list_agent_workflows()
            if not a_wfs:
                st.error(f"No workflows found for Company A. {a_api.last_error or ''}")
                st.stop()
            if not b_wfs:
                st.error(f"No workflows found for Company B. {b_api.last_error or ''}")
                st.stop()
            st.session_state["cmp_a_workflows"] = a_wfs
            st.session_state["cmp_b_workflows"] = b_wfs
            st.rerun()
        st.stop()

    a_wfs = st.session_state["cmp_a_workflows"]
    b_wfs = st.session_state["cmp_b_workflows"]

    def _wf_label(w: dict) -> str:
        wid = w.get("id") or "?"
        return f"{w.get('name', 'Unnamed')} · v{w.get('version', '?')} ({wid[:8]}…)"

    a_wf_map = {_wf_label(w): w for w in a_wfs if w.get("id")}
    b_wf_map = {_wf_label(w): w for w in b_wfs if w.get("id")}

    col_sel_a, col_sel_b = st.columns(2)
    with col_sel_a:
        a_wf_pick = st.selectbox(
            f"Workflow A — {a_company.get('name', '?')}",
            list(a_wf_map.keys()),
            key="cmp_a_wf_pick",
        )
    with col_sel_b:
        b_wf_pick = st.selectbox(
            f"Workflow B — {b_company.get('name', '?')}",
            list(b_wf_map.keys()),
            key="cmp_b_wf_pick",
        )

    if st.button("Load workflows & agents", key="cmp_load_wf_detail", type="primary"):
        with st.spinner("Fetching workflow details and agents…"):
            a_wf_full = a_api.get_agent_workflow(a_wf_map[a_wf_pick]["id"])
            b_wf_full = b_api.get_agent_workflow(b_wf_map[b_wf_pick]["id"])
            a_agents_list = a_api.list_agents()
            b_agents_list = a_agents_list if same_company else b_api.list_agents()
        if a_wf_full is None:
            st.error(f"Failed to fetch Workflow A. {a_api.last_error or ''}")
            st.stop()
        if b_wf_full is None:
            st.error(f"Failed to fetch Workflow B. {b_api.last_error or ''}")
            st.stop()
        st.session_state["cmp_a_wf_full"] = a_wf_full
        st.session_state["cmp_b_wf_full"] = b_wf_full
        st.session_state["cmp_a_agent_list"] = a_agents_list
        st.session_state["cmp_b_agent_list"] = b_agents_list
        # Clear any previously-fetched agent details so we refetch on demand
        st.session_state.pop("cmp_wf_agent_details", None)
        st.rerun()

    if "cmp_a_wf_full" not in st.session_state:
        st.stop()

    a_wf = st.session_state["cmp_a_wf_full"]
    b_wf = st.session_state["cmp_b_wf_full"]
    a_agents_list = st.session_state["cmp_a_agent_list"]
    b_agents_list = st.session_state["cmp_b_agent_list"]

    st.header("Step 3: Workflow comparison")

    meta_a, meta_b = st.columns(2)
    with meta_a:
        st.subheader(f"A · {a_wf.get('name', '?')}")
        st.json(_workflow_meta(a_wf))
    with meta_b:
        st.subheader(f"B · {b_wf.get('name', '?')}")
        st.json(_workflow_meta(b_wf))

    _text_diff(a_wf.get("description"), b_wf.get("description"), "Description")
    _json_diff(
        a_wf.get("workflowConfiguration"),
        b_wf.get("workflowConfiguration"),
        "Workflow configuration",
    )

    # Referenced agents
    st.header("Step 4: Referenced agents")

    a_refs = _resolve_referenced_agents(a_wf, a_agents_list)
    b_refs = _resolve_referenced_agents(b_wf, b_agents_list)

    a_by_name = {a.get("name"): a for a in a_refs if a.get("name")}
    b_by_name = {a.get("name"): a for a in b_refs if a.get("name")}
    all_names = sorted(set(a_by_name.keys()) | set(b_by_name.keys()))

    if not all_names:
        st.info("No agent references were detected in either workflowConfiguration.")
    else:
        st.markdown(
            f"Found **{len(a_refs)}** referenced agent(s) in Workflow A and "
            f"**{len(b_refs)}** in Workflow B (matched by name)."
        )

        summary_rows = []
        for name in all_names:
            a_agent = a_by_name.get(name)
            b_agent = b_by_name.get(name)
            row = {
                "agent name": name,
                "in A": a_agent is not None,
                "in B": b_agent is not None,
                "A version": a_agent.get("version") if a_agent else None,
                "B version": b_agent.get("version") if b_agent else None,
                "A type": a_agent.get("type") if a_agent else None,
                "B type": b_agent.get("type") if b_agent else None,
            }
            summary_rows.append(row)
        st.dataframe(pd.DataFrame(summary_rows), width="stretch", hide_index=True)

        if st.button("Fetch full detail for every matched pair & diff", key="cmp_diff_all"):
            details = {}
            pairs = [n for n in all_names if a_by_name.get(n) and b_by_name.get(n)]
            if not pairs:
                st.warning("No agents present in both workflows — nothing to diff.")
            else:
                progress = st.progress(0.0, text="Fetching agents…")
                for i, name in enumerate(pairs):
                    aid = a_by_name[name].get("id")
                    bid = b_by_name[name].get("id")
                    a_full = a_api.get_agent(aid) if aid else None
                    b_full = b_api.get_agent(bid) if bid else None
                    details[name] = {"a": a_full, "b": b_full}
                    progress.progress((i + 1) / len(pairs))
                st.session_state["cmp_wf_agent_details"] = details
                st.rerun()

        details = st.session_state.get("cmp_wf_agent_details")
        if details:
            # Divergence summary
            differing = []
            for name, pair in details.items():
                a_full = pair.get("a") or {}
                b_full = pair.get("b") or {}
                fields = {
                    "prompt": a_full.get("prompt") != b_full.get("prompt"),
                    "systemPrompt": a_full.get("systemPrompt") != b_full.get("systemPrompt"),
                    "outputFormat": a_full.get("outputFormat") != b_full.get("outputFormat"),
                    "configuration": a_full.get("configuration") != b_full.get("configuration"),
                    "model": a_full.get("model") != b_full.get("model"),
                    "type": a_full.get("type") != b_full.get("type"),
                }
                changed = [k for k, v in fields.items() if v]
                if changed:
                    differing.append({"agent": name, "differing fields": ", ".join(changed)})

            if differing:
                st.warning(f"{len(differing)} agent(s) differ between the two workflows.")
                st.dataframe(pd.DataFrame(differing), width="stretch", hide_index=True)
            else:
                st.success("All matched agents are identical.")

            for name in sorted(details.keys()):
                pair = details[name]
                a_full = pair.get("a") or {}
                b_full = pair.get("b") or {}
                differs_here = any([
                    a_full.get("prompt") != b_full.get("prompt"),
                    a_full.get("systemPrompt") != b_full.get("systemPrompt"),
                    a_full.get("outputFormat") != b_full.get("outputFormat"),
                    a_full.get("configuration") != b_full.get("configuration"),
                    a_full.get("model") != b_full.get("model"),
                ])
                icon = "❗️" if differs_here else "✅"
                with st.expander(f"{icon} {name}", expanded=differs_here):
                    if not a_full or not b_full:
                        st.error("Could not fetch full detail for one side.")
                        continue
                    meta_a, meta_b = st.columns(2)
                    with meta_a:
                        st.markdown(f"**A · {a_full.get('name', '?')}**")
                        st.json(_agent_meta(a_full))
                    with meta_b:
                        st.markdown(f"**B · {b_full.get('name', '?')}**")
                        st.json(_agent_meta(b_full))
                    _text_diff(a_full.get("prompt"), b_full.get("prompt"), "Prompt")
                    _text_diff(a_full.get("systemPrompt"), b_full.get("systemPrompt"), "System prompt")
                    _json_diff(
                        a_full.get("outputFormat"),
                        b_full.get("outputFormat"),
                        "Response object (outputFormat)",
                    )
                    _json_diff(
                        a_full.get("configuration"),
                        b_full.get("configuration"),
                        "Configuration",
                    )

    with st.expander("Full Workflow A JSON"):
        st.json(a_wf)
    with st.expander("Full Workflow B JSON"):
        st.json(b_wf)
