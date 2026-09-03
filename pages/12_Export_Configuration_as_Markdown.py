import io
import json
import re
import zipfile

import pandas as pd
import streamlit as st

from auth import HypatosAPI
from config import BASE_URL_EU, BASE_URL_US

st.set_page_config(page_title="Export Configuration as Markdown", layout="wide")
st.title("Export Configuration as Markdown")
st.caption(
    "Fetch a company's configuration for a set of projects — composite enrichment "
    "workflows, the dynamic agent workflow with all its agents, and routing rules — and "
    "download it as a bundle of Markdown files (one per artefact)."
)


UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _reset(prefix: str = "exp_"):
    for key in list(st.session_state.keys()):
        if key.startswith(prefix):
            st.session_state.pop(key, None)


def _slug(text: str, fallback: str = "item") -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or fallback


def _fence(text: str, lang: str = "") -> str:
    """Wrap text in a code fence longer than any backtick run it contains."""
    text = "" if text is None else str(text)
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{lang}\n{text}\n{ticks}"


def _find_uuids(node) -> set:
    found = set()
    if isinstance(node, dict):
        for v in node.values():
            found |= _find_uuids(v)
    elif isinstance(node, list):
        for v in node:
            found |= _find_uuids(v)
    elif isinstance(node, str):
        found.update(UUID_RE.findall(node))
    return found


def _resolve_referenced_agents(wf_detail: dict, agents: list) -> list:
    """Agents referenced by wf_detail.workflowConfiguration, matched on UUID and
    on name:version / quoted-name substrings (same approach as the compare page)."""
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
        needles = [f'"{name}"']
        if version:
            needles.append(f"{name}:{version}")
        if any(n in config_str for n in needles):
            hits.append(a)
            seen.add(a.get("id"))
    return hits


col_reset_l, col_reset_r = st.columns([5, 1])
with col_reset_r:
    if st.button("Reset", key="exp_reset"):
        _reset()
        st.rerun()


# ---------------------------------------------------------------------------
# Step 1 — Credentials
# ---------------------------------------------------------------------------
st.header("Step 1: Credentials")
st.markdown(
    "One company only. Required scopes: `projects.read`, `agents.read`, "
    "`enrichment-workflows.read` and `routings.read`."
)

env = st.selectbox(
    "Region",
    (BASE_URL_EU, BASE_URL_US),
    key="exp_env",
    format_func=lambda u: "EU" if u == BASE_URL_EU else "US",
)
client_id = st.text_input("client_id", key="exp_id")
client_secret = st.text_input("client_secret", type="password", key="exp_secret")

if not st.session_state.get("exp_authed"):
    if st.button("Authenticate", key="exp_auth"):
        if not (client_id and client_secret):
            st.error("Please provide client_id and client_secret.")
        else:
            api = HypatosAPI(client_id.strip(), client_secret.strip(), env)
            if not api.authenticate():
                st.error(f"Authentication failed. {api.last_error or ''}")
                st.stop()
            company = api.get_company()
            if not company:
                st.error(f"Authenticated but could not fetch the company. {api.last_error or ''}")
                st.stop()
            st.session_state["exp_api"] = api
            st.session_state["exp_company"] = company
            st.session_state["exp_authed"] = True
            st.rerun()
    st.stop()

api: HypatosAPI = st.session_state["exp_api"]
company = st.session_state["exp_company"]
st.success(f"**{company.get('name', '?')}** (`{company.get('id', '?')}`)")


# ---------------------------------------------------------------------------
# Step 2 — Select projects
# ---------------------------------------------------------------------------
st.header("Step 2: Select projects")

if "exp_projects" not in st.session_state:
    if st.button("Load projects", key="exp_load_projects"):
        with st.spinner("Fetching projects…"):
            data = api.get_projects() or {}
        projects = data.get("data", [])
        if not projects:
            st.error("No projects found, or the fetch failed.")
            st.stop()
        st.session_state["exp_projects"] = projects
        st.rerun()
    st.stop()

projects = st.session_state["exp_projects"]
project_names = {p.get("id"): p.get("name") for p in projects if p.get("id")}

options = [(p.get("id"), p.get("name") or "(unnamed)") for p in projects if p.get("id")]
options.sort(key=lambda x: (x[1] or "").lower())
selected = st.multiselect(
    "Projects",
    options,
    format_func=lambda x: x[1],
    key="exp_selected",
)

if not selected:
    st.info("Select at least one project.")
    st.stop()

selected_ids = {pid for pid, _ in selected}


# ---------------------------------------------------------------------------
# Step 3 — Fetch configuration
# ---------------------------------------------------------------------------
st.header("Step 3: Fetch configuration")

if st.button("Fetch configuration for the selected projects", type="primary", key="exp_fetch"):
    with st.spinner("Fetching enrichment workflows, agent workflows, agents and routing rules…"):
        # Composite enrichment workflows bound to the selected projects.
        all_enrichment = api.list_enrichment_workflows()
        enrichment = [
            w for w in all_enrichment
            if selected_ids & set(w.get("projectIds") or [])
        ]

        # Dynamic (agent) workflows assigned to the selected projects.
        agent_workflows = {}
        for pid in selected_ids:
            for w in api.list_agent_workflows(project_id=pid):
                if w.get("id"):
                    agent_workflows.setdefault(w["id"], w)
        workflow_details = {}
        for wid in agent_workflows:
            detail = api.get_agent_workflow(wid)
            if detail:
                workflow_details[wid] = detail

        # Agents referenced by those workflows (full detail for the prompts).
        agent_summaries = api.list_agents()
        referenced = {}
        for detail in workflow_details.values():
            for a in _resolve_referenced_agents(detail, agent_summaries):
                if a.get("id"):
                    referenced.setdefault(a["id"], a)
        agent_details = {}
        for aid in referenced:
            full = api.get_agent(aid)
            if full:
                agent_details[aid] = full

        # Routing rules touching the selected projects.
        routing_rules = []
        for rid in api.get_all_routing_rule_ids(limit=50):
            rule = api.get_routing_by_id(rid)
            if not rule:
                continue
            if rule.get("fromProjectId") in selected_ids or rule.get("toProjectId") in selected_ids:
                routing_rules.append(rule)

    st.session_state["exp_fetched"] = {
        "enrichment": enrichment,
        "workflows": list(workflow_details.values()),
        "agents": list(agent_details.values()),
        "routing_rules": routing_rules,
    }
    st.rerun()

fetched = st.session_state.get("exp_fetched")
if not fetched:
    st.stop()

enrichment = fetched["enrichment"]
workflows = fetched["workflows"]
agents = fetched["agents"]
routing_rules = fetched["routing_rules"]

st.dataframe(
    pd.DataFrame(
        [
            {"artefact": "Composite enrichment workflows", "count": len(enrichment)},
            {"artefact": "Dynamic (agent) workflows", "count": len(workflows)},
            {"artefact": "Agents", "count": len(agents)},
            {"artefact": "Routing rules", "count": len(routing_rules)},
        ]
    ),
    width="stretch",
    hide_index=True,
)

if not any([enrichment, workflows, agents, routing_rules]):
    st.warning("Nothing was found for the selected projects.")
    st.stop()


# ---------------------------------------------------------------------------
# Step 4 — Markdown generation
# ---------------------------------------------------------------------------
def _project_list_md(project_ids) -> str:
    if not project_ids:
        return "_none_"
    return "\n".join(
        f"- {project_names.get(pid, '(unknown project)')} (`{pid}`)" for pid in project_ids
    )


def _enrichment_md(w: dict) -> str:
    lines = [
        f"# Composite enrichment workflow: {w.get('name', '(unnamed)')}",
        "",
        f"- **id:** `{w.get('id', '?')}`",
        f"- **version:** {w.get('versionString') or w.get('version') or '?'}",
        f"- **updatedAt:** {w.get('updatedAt', '?')}",
        "",
        "## Description",
        "",
        (w.get("description") or "_none_"),
        "",
        "## Assigned projects",
        "",
        _project_list_md(w.get("projectIds") or []),
        "",
        "## Definition (YAML)",
        "",
        _fence(w.get("definition") or "", "yaml"),
        "",
    ]
    return "\n".join(lines)


def _workflow_md(w: dict) -> str:
    meta = {
        "id": w.get("id"),
        "name": w.get("name"),
        "version": w.get("version"),
        "model": w.get("model"),
        "workflowType": w.get("workflowType"),
        "projects": w.get("projects"),
        "trainingProjects": w.get("trainingProjects"),
    }
    lines = [
        f"# Dynamic workflow: {w.get('name', '(unnamed)')}",
        "",
        f"- **id:** `{w.get('id', '?')}`",
        f"- **version:** {w.get('version', '?')}",
        f"- **model:** {w.get('model', '?')}",
        f"- **workflowType:** {w.get('workflowType', '?')}",
        "",
        "## Description",
        "",
        (w.get("description") or "_none_"),
        "",
        "## Metadata",
        "",
        _fence(json.dumps(meta, indent=2, ensure_ascii=False), "json"),
        "",
        "## Workflow configuration",
        "",
        _fence(json.dumps(w.get("workflowConfiguration") or {}, indent=2, ensure_ascii=False), "json"),
        "",
    ]
    return "\n".join(lines)


def _agent_md(a: dict) -> str:
    lines = [
        f"# Agent: {a.get('name', '(unnamed)')}",
        "",
        f"- **id:** `{a.get('id', '?')}`",
        f"- **version:** {a.get('version', '?')}",
        f"- **type:** {a.get('type', '?')}",
        f"- **model:** {a.get('model', '?')}",
        "",
        "## Description",
        "",
        (a.get("description") or "_none_"),
        "",
        "## System prompt",
        "",
        _fence(a.get("systemPrompt") or "", "text"),
        "",
        "## User prompt",
        "",
        _fence(a.get("prompt") or "", "text"),
        "",
    ]
    return "\n".join(lines)


def _routing_md(rules: list) -> str:
    lines = [f"# Routing rules ({len(rules)})", ""]
    for rule in rules:
        frm = rule.get("fromProjectId")
        to = rule.get("toProjectId")
        lines += [
            f"## {project_names.get(frm, frm)} → {project_names.get(to, to)}",
            "",
            f"- **id:** `{rule.get('id', '?')}`",
            f"- **from:** {project_names.get(frm, '(unknown)')} (`{frm}`)",
            f"- **to:** {project_names.get(to, '(unknown)')} (`{to}`)",
            "",
            _fence(json.dumps(rule, indent=2, ensure_ascii=False), "json"),
            "",
        ]
    return "\n".join(lines)


def _index_md() -> str:
    selected_lines = "\n".join(
        f"- {name} (`{pid}`)" for pid, name in sorted(selected, key=lambda x: (x[1] or "").lower())
    )
    lines = [
        f"# Configuration export — {company.get('name', '?')}",
        "",
        f"- **company id:** `{company.get('id', '?')}`",
        f"- **projects exported:** {len(selected)}",
        "",
        "## Projects",
        "",
        selected_lines,
        "",
        "## Contents",
        "",
        f"- `enrichment/` — {len(enrichment)} composite enrichment workflow(s)",
        f"- `workflows/` — {len(workflows)} dynamic (agent) workflow(s)",
        f"- `agents/` — {len(agents)} agent(s)",
        f"- `routing_rules.md` — {len(routing_rules)} routing rule(s)",
        "",
    ]
    return "\n".join(lines)


def _unique_name(base: str, used: set) -> str:
    name = base
    i = 2
    while name in used:
        name = f"{base}-{i}"
        i += 1
    used.add(name)
    return name


def _build_files() -> dict:
    files = {"README.md": _index_md()}
    used = set()
    for w in enrichment:
        slug = _unique_name(_slug(w.get("name"), "enrichment"), used)
        files[f"enrichment/{slug}.md"] = _enrichment_md(w)
    used = set()
    for w in workflows:
        slug = _unique_name(_slug(w.get("name"), "workflow"), used)
        files[f"workflows/{slug}.md"] = _workflow_md(w)
    used = set()
    for a in agents:
        slug = _unique_name(_slug(a.get("name"), "agent"), used)
        files[f"agents/{slug}.md"] = _agent_md(a)
    if routing_rules:
        files["routing_rules.md"] = _routing_md(routing_rules)
    return files


st.header("Step 4: Download")

files = _build_files()
st.caption(f"{len(files)} Markdown file(s) will be bundled into the ZIP.")

with st.expander("Files in the bundle"):
    for path in sorted(files):
        st.markdown(f"- `{path}`")

buffer = io.BytesIO()
with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
    for path, content in files.items():
        zf.writestr(path, content)
buffer.seek(0)

zip_name = f"{_slug(company.get('name'), 'company')}-config.zip"
st.download_button(
    "Download Markdown bundle (.zip)",
    data=buffer.getvalue(),
    file_name=zip_name,
    mime="application/zip",
    type="primary",
    key="exp_download",
)

# Let the user preview any single file without downloading.
with st.expander("Preview a file"):
    pick = st.selectbox("File", sorted(files), key="exp_preview_pick")
    if pick:
        st.code(files[pick], language="markdown")
