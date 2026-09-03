import re

import pandas as pd
import requests
import streamlit as st

from auth import HypatosAPI
from config import BASE_URL_EU, BASE_URL_US

st.set_page_config(page_title="Deploy new OOTB Setup", page_icon=":rocket:", layout="wide")
st.title("🚀 Deploy new OOTB Setup")
st.caption(
    "Clone a complete out-of-the-box setup — its projects, routing rules, composite "
    "enrichment workflows and agentic workflows (with agents) — from the template company "
    "into a target company in one go."
)


# ---------------------------------------------------------------------------
# OOTB setup catalogue
# ---------------------------------------------------------------------------
# The project ids that make up each setup live in .streamlit/secrets.toml under
# [ootb.setups.*]. This dict is the shape / fallback; secrets override it.
def _empty_setup(label, group):
    return {
        "label": label,
        "group": group,
        "project_ids": [],
        "enrichment_workflow_ids": [],
        "agent_workflow_ids": [],
    }


DEFAULT_SETUPS = {
    "invoice_processing_a": _empty_setup("Invoice Processing — Setup A", "Invoice Processing"),
    "invoice_processing_b": _empty_setup("Invoice Processing — Setup B", "Invoice Processing"),
    "order_confirmation": _empty_setup("Order Confirmation", "Order Confirmation"),
    "order_management": _empty_setup("Order Management", "Order Management"),
}


def _load_setups() -> dict:
    """Merge the DEFAULT_SETUPS shape with whatever secrets provide."""
    setups = {k: dict(v) for k, v in DEFAULT_SETUPS.items()}
    try:
        cfg = st.secrets["ootb"]["setups"]
    except Exception:
        return setups
    for key, val in dict(cfg).items():
        base = dict(setups.get(key, _empty_setup(key, "Other")))
        base["label"] = val.get("label", base.get("label", key))
        base["group"] = val.get("group", base.get("group", "Other"))
        base["project_ids"] = [str(p) for p in (val.get("project_ids") or [])]
        base["enrichment_workflow_ids"] = [str(p) for p in (val.get("enrichment_workflow_ids") or [])]
        base["agent_workflow_ids"] = [str(p) for p in (val.get("agent_workflow_ids") or [])]
        setups[key] = base
    return setups


def _source_region() -> str:
    try:
        region = str(st.secrets["ootb"]["source_region"]).strip().upper()
    except Exception:
        region = "EU"
    return BASE_URL_US if region == "US" else BASE_URL_EU


# ---------------------------------------------------------------------------
# Copy helpers (patterns proven on the Clone / Copy Agent Workflow pages)
# ---------------------------------------------------------------------------
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

AGENT_STRIP = {
    "id", "rootAgentId", "companyId",
    "createdAt", "createdBy", "updatedAt", "updatedBy",
    "versions", "versionsMetadata",
    "isOotb", "sourceTemplateAgentId", "sourceTemplateAgentVersion",
}
WORKFLOW_STRIP = {
    "id", "companyId",
    "createdAt", "createdBy", "updatedAt", "updatedBy",
    "version",
    "isOotb", "sourceWorkflowId", "sourceWorkflowVersion",
}
ENRICHMENT_FIELDS = ("name", "definition", "description", "projectIds")

# Always-available base model to fall back to when an agent's own model is not
# active in the target company (create_agent -> 422 "Model is not active ...").
BASE_MODEL_ID = "3548e0ca-e5e4-4c1a-8ca2-a0878036053e"


def _is_model_inactive(err: str) -> bool:
    if not err:
        return False
    e = err.lower()
    return "422" in e and "model" in e and "not active" in e


def _set_model(payload: dict, model_id: str):
    matched = False
    for key in ("model", "modelId"):
        if key in payload:
            payload[key] = model_id
            matched = True
    if not matched:
        payload["model"] = model_id


def _sanitize(obj: dict, strip_keys: set) -> dict:
    return {k: v for k, v in obj.items() if k not in strip_keys}


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


def _rewrite_uuids(node, mapping: dict):
    """Deep copy with any source id in `mapping` swapped for its replacement."""
    if isinstance(node, dict):
        return {k: _rewrite_uuids(v, mapping) for k, v in node.items()}
    if isinstance(node, list):
        return [_rewrite_uuids(v, mapping) for v in node]
    if isinstance(node, str):
        out = node
        for src, dst in mapping.items():
            if src and src in out:
                out = out.replace(src, dst)
        return out
    return node


def _remap_project_ref(value, pmap: dict):
    """Remap a workflow `projects` / `trainingProjects` field (list or comma string)
    to target ids, keeping only ids present in the mapping."""
    if isinstance(value, list):
        return [pmap[v] for v in value if v in pmap]
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",") if p.strip()]
        return ",".join(pmap[p] for p in parts if p in pmap)
    return value


def _resolve_referenced_agents(wf_detail: dict, agents: list) -> list:
    """Agents referenced by wf_detail.workflowConfiguration (UUID + name:version scan)."""
    import json

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


def _reset(prefix: str = "ootb_"):
    for key in list(st.session_state.keys()):
        if key.startswith(prefix):
            st.session_state.pop(key, None)


col_reset_l, col_reset_r = st.columns([5, 1])
with col_reset_r:
    if st.button("Reset", key="ootb_reset"):
        _reset()
        st.rerun()


# ---------------------------------------------------------------------------
# Step 1 — Authenticate template (source, from secrets) + target
# ---------------------------------------------------------------------------
st.header("Step 1: Credentials")
st.markdown(
    "The **template** (source) company credentials are pre-configured in secrets. "
    "Provide the **target** company credentials. Required scopes: `projects.read/write`, "
    "`routings.read/write`, `agents.read/write`, `enrichment-workflows.read/write`, "
    "`companies.read`."
)

try:
    src_client_id = str(st.secrets["CLIENT_ID"])
    src_client_secret = str(st.secrets["CLIENT_SECRET"])
    _secrets_ok = bool(src_client_id and src_client_secret)
except Exception:
    _secrets_ok = False

if not _secrets_ok:
    st.error("Template credentials (`CLIENT_ID` / `CLIENT_SECRET`) are not configured in secrets.")
    st.stop()

col_src, col_tgt = st.columns(2)
with col_src:
    st.subheader("Template company (source)")
    st.info("Credentials pre-configured from secrets.")
    src_env = st.selectbox(
        "Template API Region",
        (BASE_URL_EU, BASE_URL_US),
        index=0 if _source_region() == BASE_URL_EU else 1,
        key="ootb_src_env",
        format_func=lambda u: "EU" if u == BASE_URL_EU else "US",
    )
with col_tgt:
    st.subheader("Target company")
    tgt_env = st.selectbox(
        "Target API Region",
        (BASE_URL_EU, BASE_URL_US),
        key="ootb_tgt_env",
        format_func=lambda u: "EU" if u == BASE_URL_EU else "US",
    )
    tgt_id = st.text_input("Target client_id", key="ootb_tgt_id")
    tgt_secret = st.text_input("Target client_secret", type="password", key="ootb_tgt_secret")

if not st.session_state.get("ootb_authed"):
    if st.button("Authenticate", key="ootb_auth"):
        if not (tgt_id and tgt_secret):
            st.error("Please provide the target client_id and client_secret.")
            st.stop()
        src_api = HypatosAPI(src_client_id.strip(), src_client_secret.strip(), src_env)
        if not src_api.authenticate():
            st.error(f"Template authentication failed. {src_api.last_error or ''}")
            st.stop()
        src_company = src_api.get_company()
        if not src_company:
            st.error(f"Template authenticated but company could not be fetched. {src_api.last_error or ''}")
            st.stop()
        tgt_api = HypatosAPI(tgt_id.strip(), tgt_secret.strip(), tgt_env)
        if not tgt_api.authenticate():
            st.error(f"Target authentication failed. {tgt_api.last_error or ''}")
            st.stop()
        tgt_company = tgt_api.get_company()
        if not tgt_company:
            st.error(f"Target authenticated but company could not be fetched. {tgt_api.last_error or ''}")
            st.stop()
        if src_company.get("id") == tgt_company.get("id"):
            st.error("Target company must be different from the template company.")
            st.stop()
        st.session_state["ootb_src_api"] = src_api
        st.session_state["ootb_tgt_api"] = tgt_api
        st.session_state["ootb_src_company"] = src_company
        st.session_state["ootb_tgt_company"] = tgt_company
        st.session_state["ootb_authed"] = True
        st.rerun()
    st.stop()

src_api: HypatosAPI = st.session_state["ootb_src_api"]
tgt_api: HypatosAPI = st.session_state["ootb_tgt_api"]
src_company = st.session_state["ootb_src_company"]
tgt_company = st.session_state["ootb_tgt_company"]

st.success(
    f"Template: **{src_company.get('name', '?')}** (`{src_company.get('id', '?')}`) → "
    f"Target: **{tgt_company.get('name', '?')}** (`{tgt_company.get('id', '?')}`)"
)


# ---------------------------------------------------------------------------
# Step 2 — Target model id + naming
# ---------------------------------------------------------------------------
st.header("Step 2: Target project defaults")

if "ootb_tgt_projects" not in st.session_state:
    if st.button("Load target projects (for model id)", key="ootb_load_tgt"):
        data = tgt_api.get_projects() or {}
        st.session_state["ootb_tgt_projects"] = data.get("data", [])
        st.rerun()
    st.stop()

tgt_projects = st.session_state["ootb_tgt_projects"]
if not tgt_projects:
    st.error(
        "No projects in the target company. Create one project there (with the correct model "
        "setup) so its extraction model id can be reused, then reload."
    )
    st.stop()

with st.expander("How to find the model id"):
    st.write(
        "Pick a target project that already has the correct model setup (e.g. Hypatos AI Agent, "
        "Invoice EU/US datapoints). Its extraction model id is applied to every cloned project."
    )

tgt_proj_options = [(p.get("id"), p.get("name")) for p in tgt_projects]
model_proj = st.selectbox(
    "Target project for the model id",
    tgt_proj_options,
    format_func=lambda x: x[1],
    key="ootb_model_proj",
)
model_id = None
for p in tgt_projects:
    if p.get("id") == model_proj[0]:
        model_id = p.get("extractionModelId")
        break
st.write(f"Model id: `{model_id}`")

col_pre, col_suf = st.columns(2)
with col_pre:
    name_prefix = st.text_input("Project name prefix", key="ootb_prefix")
with col_suf:
    name_suffix = st.text_input("Project name suffix", key="ootb_suffix")


# ---------------------------------------------------------------------------
# Step 3 — Choose the OOTB setup
# ---------------------------------------------------------------------------
st.header("Step 3: Choose the OOTB setup")

setups = _load_setups()
groups = {}
for key, s in setups.items():
    groups.setdefault(s["group"], []).append(key)

group_choice = st.selectbox("Category", sorted(groups.keys()), key="ootb_group")
setup_keys = groups[group_choice]
setup_key = st.radio(
    "Setup",
    setup_keys,
    format_func=lambda k: setups[k]["label"],
    key="ootb_setup_key",
)

setup = setups[setup_key]
setup_project_ids = setup["project_ids"]
setup_enrichment_ids = setup["enrichment_workflow_ids"]
setup_agent_workflow_ids = setup["agent_workflow_ids"]

if not setup_project_ids:
    st.warning(
        f"**{setup['label']}** has no project ids configured. Add them under "
        f"`[ootb.setups.{setup_key}]` → `project_ids` in secrets.toml."
    )
    st.stop()

st.caption(
    f"**{setup['label']}** → {len(setup_project_ids)} project(s), "
    f"{len(setup_enrichment_ids)} enrichment workflow(s), "
    f"{len(setup_agent_workflow_ids)} agentic workflow(s) configured."
)
if not setup_enrichment_ids and not setup_agent_workflow_ids:
    st.info(
        "No `enrichment_workflow_ids` / `agent_workflow_ids` configured for this setup — "
        "the page will fall back to discovering them from the project bindings, which may find "
        "nothing if the template workflows are not bound to these projects. Add the ids under "
        f"`[ootb.setups.{setup_key}]` in secrets.toml for a reliable clone."
    )


# ---------------------------------------------------------------------------
# Step 4 — Pre-flight check
# ---------------------------------------------------------------------------
st.header("Step 4: Pre-flight check")
st.markdown(
    "Reads the template and target (no writes) to show exactly what would be created and to "
    "catch **agent name/version collisions** in the target before anything is cloned."
)

if st.button("Run pre-flight check", key="ootb_preflight"):
    with st.spinner("Inspecting template and target…"):
        # Source projects.
        src_project_names = {}
        missing_projects = []
        for pid in setup_project_ids:
            detail = src_api.get_project_by_id(pid)
            if detail:
                src_project_names[pid] = detail.get("name")
            else:
                missing_projects.append(pid)

        setup_id_set = set(setup_project_ids)
        missing_enrichment = []
        missing_workflows = []

        # Enrichment workflows: explicit ids from config, else discover by project binding.
        if setup_enrichment_ids:
            enrichment = []
            for wid in setup_enrichment_ids:
                wf = src_api.get_enrichment_workflow(wid)
                if wf:
                    enrichment.append(wf)
                else:
                    missing_enrichment.append({"id": wid, "error": src_api.last_error or "not found (HTTP 404)"})
        else:
            enrichment = [
                w for w in src_api.list_enrichment_workflows()
                if setup_id_set & set(w.get("projectIds") or [])
            ]

        # Agentic workflows: explicit ids from config, else discover by project binding.
        workflows = []
        if setup_agent_workflow_ids:
            for wid in setup_agent_workflow_ids:
                detail = src_api.get_agent_workflow(wid)
                if detail:
                    workflows.append(detail)
                else:
                    missing_workflows.append({"id": wid, "error": src_api.last_error or "not found (HTTP 404)"})
        else:
            wf_summaries = {}
            for pid in setup_project_ids:
                for w in src_api.list_agent_workflows(project_id=pid):
                    if w.get("id"):
                        wf_summaries.setdefault(w["id"], w)
            for wid in wf_summaries:
                detail = src_api.get_agent_workflow(wid)
                if detail:
                    workflows.append(detail)

        src_agents = src_api.list_agents()
        referenced = {}
        for wf in workflows:
            for a in _resolve_referenced_agents(wf, src_agents):
                if a.get("id"):
                    referenced.setdefault(a["id"], a)
        agents = {}
        for aid in referenced:
            full = src_api.get_agent(aid)
            if full:
                agents[aid] = full

        # Target-side collision detection (agents by name:version).
        tgt_agents = tgt_api.list_agents()
        tgt_agent_keys = {
            (a.get("name"), str(a.get("version"))) for a in tgt_agents
        }
        agent_collisions = [
            {"name": a.get("name"), "version": a.get("version")}
            for a in agents.values()
            if (a.get("name"), str(a.get("version"))) in tgt_agent_keys
        ]

        # Enrichment name collisions (reported, will be skipped, not a hard stop).
        tgt_enrich_names = {w.get("name") for w in tgt_api.list_enrichment_workflows()}

    st.session_state["ootb_plan"] = {
        "setup_key": setup_key,
        "src_project_names": src_project_names,
        "missing_projects": missing_projects,
        "missing_enrichment": missing_enrichment,
        "missing_workflows": missing_workflows,
        "enrichment": enrichment,
        "workflows": workflows,
        "agents": agents,
        "src_agent_index": [
            {"id": a.get("id"), "name": a.get("name"), "version": a.get("version")}
            for a in src_agents if a.get("id")
        ],
        "agent_collisions": agent_collisions,
        "enrich_collisions": [w.get("name") for w in enrichment if w.get("name") in tgt_enrich_names],
        "model_id": model_id,
        "prefix": name_prefix,
        "suffix": name_suffix,
    }
    # Clear any earlier step results so the plan and its steps start fresh.
    for k in (
        "ootb_results", "ootb_project_map", "ootb_res_projects", "ootb_res_routings",
        "ootb_res_enrichment", "ootb_agent_map", "ootb_res_agents", "ootb_res_workflows",
    ):
        st.session_state.pop(k, None)
    st.rerun()

plan = st.session_state.get("ootb_plan")
if not plan or plan.get("setup_key") != setup_key:
    st.info("Run the pre-flight check to see the deploy plan.")
    st.stop()

st.subheader("Deploy plan")
st.dataframe(
    pd.DataFrame([
        {"artefact": "Projects", "count": len(setup_project_ids)},
        {"artefact": "Composite enrichment workflows", "count": len(plan["enrichment"])},
        {"artefact": "Agentic workflows", "count": len(plan["workflows"])},
        {"artefact": "Agents", "count": len(plan["agents"])},
    ]),
    width="stretch",
    hide_index=True,
)

if plan["missing_projects"]:
    st.warning(
        "These configured project ids were not found in the template company and will be "
        "skipped: " + ", ".join(f"`{p}`" for p in plan["missing_projects"])
    )

if plan.get("missing_enrichment"):
    st.warning(
        "These configured `enrichment_workflow_ids` could not be fetched from the template "
        "company. An **HTTP 403** means the template credentials are missing the "
        "`enrichment-workflows.read` scope; an **HTTP 404** means the id does not exist in "
        "this company / region."
    )
    st.dataframe(pd.DataFrame(plan["missing_enrichment"]), width="stretch", hide_index=True)

if plan.get("missing_workflows"):
    st.warning(
        "These configured `agent_workflow_ids` could not be fetched from the template company. "
        "An **HTTP 403** means the template credentials are missing the `agents.read` scope; an "
        "**HTTP 404** means the id does not exist in this company / region."
    )
    st.dataframe(pd.DataFrame(plan["missing_workflows"]), width="stretch", hide_index=True)

if plan["enrich_collisions"]:
    st.warning(
        "Target already has enrichment workflow(s) with these names — they will be **skipped**: "
        + ", ".join(plan["enrich_collisions"])
    )

deploy_blocked = bool(plan["agent_collisions"])
if deploy_blocked:
    st.error(
        "**Agent name/version collisions in the target — deploy is blocked.** "
        "Delete or rename these agents in the target company, then re-run the pre-flight check."
    )
    st.dataframe(pd.DataFrame(plan["agent_collisions"]), width="stretch", hide_index=True)
else:
    st.success("No agent collisions in the target. Ready to deploy.")


# ---------------------------------------------------------------------------
# Step 5 — Deploy (run each step on its own; every step persists and re-runs)
# ---------------------------------------------------------------------------
st.header("Step 5: Deploy")
st.caption(
    "Run the steps in order. Each stores its result, so a failed step (e.g. the agentic "
    "workflows) can be re-run without redoing the earlier ones. To start over cleanly, delete "
    "the created artefacts in the target and re-run the pre-flight check."
)

# Gate the steps independently: projects need a model id; agents/workflows are
# blocked only by agent collisions in the target.
model_missing = not model_id
agents_blocked = bool(plan["agent_collisions"])
if model_missing:
    st.warning("The selected target project has no extraction model id — the Projects step is disabled. Pick a different target project in Step 2.")


def _affix(name: str) -> str:
    return f"{name_prefix or ''}{name or ''}{name_suffix or ''}"


def _result_table(rows):
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.caption("_no items_")


# ----- 1. Projects -----
def _copy_projects():
    headers = tgt_api.get_headers()
    create_url = f"{tgt_api.base_url}/projects"
    project_map, rows = {}, []
    for pid in setup_project_ids:
        name = plan["src_project_names"].get(pid, pid)
        detail = src_api.get_project_by_id(pid)
        schema = src_api.get_project_schema(pid)
        if not (detail and schema):
            rows.append({"source project": name, "status": "❌ source fetch failed"})
            continue
        payload = {
            "name": _affix(detail.get("name")),
            "note": detail.get("note", ""),
            "ocr": detail.get("ocr", {}),
            "extractionModelId": model_id,
            "completion": detail.get("completion", "manual"),
            "duplicates": detail.get("duplicates", "allow"),
            "members": {"allow": "all"},
            "schema": schema,
            "retentionDays": detail.get("retentionDays", 180),
        }
        resp = requests.post(create_url, json=payload, headers=headers)
        if resp.status_code == 201:
            new_id = resp.json().get("id")
            project_map[pid] = new_id
            rows.append({"source project": name, "target project": payload["name"], "status": "✅ created", "new id": new_id})
        else:
            rows.append({"source project": name, "target project": payload["name"], "status": f"❌ HTTP {resp.status_code}: {resp.text[:300]}"})
    return project_map, rows


st.subheader("1) Projects")
if st.button("Copy projects", key="ootb_s_projects", disabled=model_missing):
    with st.spinner("Copying projects…"):
        pmap, rows = _copy_projects()
    st.session_state["ootb_project_map"] = pmap
    st.session_state["ootb_res_projects"] = rows
    st.rerun()
if st.session_state.get("ootb_res_projects") is not None:
    _result_table(st.session_state["ootb_res_projects"])
    st.caption(f"Project id map: {len(st.session_state.get('ootb_project_map', {}))} project(s) mapped.")

project_map = st.session_state.get("ootb_project_map")


# ----- 2. Routing rules -----
def _copy_routings(project_map):
    rows = []
    for rid in src_api.get_all_routing_rule_ids(limit=50):
        rule = src_api.get_routing_by_id(rid)
        if not rule:
            continue
        frm, to = rule.get("fromProjectId"), rule.get("toProjectId")
        if frm not in project_map or to not in project_map:
            continue
        new_rule = dict(rule)
        new_rule["fromProjectId"] = project_map[frm]
        new_rule["toProjectId"] = project_map[to]
        for f in ("id", "createdAt", "updatedAt"):
            new_rule.pop(f, None)
        created = tgt_api.create_routing_rule(new_rule)
        route = f"{plan['src_project_names'].get(frm, frm)} → {plan['src_project_names'].get(to, to)}"
        rows.append({
            "route": route,
            "status": "✅ created" if created else f"❌ {tgt_api.last_error or 'failed'}",
            "new id": created.get("id") if created else None,
        })
    return rows


st.subheader("2) Routing rules")
if not project_map:
    st.info("Copy the projects first — routing rules need the project id map.")
else:
    if st.button("Copy routing rules", key="ootb_s_routings"):
        with st.spinner("Copying routing rules…"):
            st.session_state["ootb_res_routings"] = _copy_routings(project_map)
        st.rerun()
    if st.session_state.get("ootb_res_routings") is not None:
        _result_table(st.session_state["ootb_res_routings"])


# ----- 3. Composite enrichment -----
def _copy_enrichment(project_map):
    tgt_names = {w.get("name") for w in tgt_api.list_enrichment_workflows()}
    rows = []
    for wf in plan["enrichment"]:
        if wf.get("name") in tgt_names:
            rows.append({"workflow": wf.get("name"), "status": "skipped (name exists)"})
            continue
        fresh = src_api.get_enrichment_workflow(wf.get("id")) or wf
        remapped = [project_map[p] for p in (fresh.get("projectIds") or []) if p in project_map]
        payload = {k: fresh.get(k) for k in ENRICHMENT_FIELDS if fresh.get(k) is not None}
        payload["projectIds"] = remapped
        created = tgt_api.create_enrichment_workflow(payload)
        rows.append({
            "workflow": payload.get("name"),
            "projects bound": len(remapped),
            "status": "✅ created" if created else f"❌ {tgt_api.last_error or 'failed'}",
            "new id": created.get("id") if created else None,
        })
    return rows


st.subheader("3) Composite enrichment workflows")
if not project_map:
    st.info("Copy the projects first — enrichment projectIds are remapped via the project id map.")
elif not plan["enrichment"]:
    st.caption("No enrichment workflows in this setup.")
else:
    if st.button("Copy composite enrichment", key="ootb_s_enrichment"):
        with st.spinner("Copying enrichment workflows…"):
            st.session_state["ootb_res_enrichment"] = _copy_enrichment(project_map)
        st.rerun()
    if st.session_state.get("ootb_res_enrichment") is not None:
        _result_table(st.session_state["ootb_res_enrichment"])


# ----- 4. Agents -----
def _copy_agents():
    agent_map, rows = {}, []
    for sid, full in plan["agents"].items():
        payload = _sanitize(full, AGENT_STRIP)
        if not payload.get("version"):
            payload.pop("version", None)
        created = tgt_api.create_agent(payload)
        note = ""
        if created is None and _is_model_inactive(tgt_api.last_error):
            _set_model(payload, BASE_MODEL_ID)
            retried = tgt_api.create_agent(payload)
            if retried is not None:
                created = retried
                note = " (model not active — reassigned to base model)"
        if created:
            agent_map[sid] = created.get("id")
            rows.append({"agent": full.get("name"), "src version": full.get("version"),
                         "new version": created.get("version"), "status": "✅ created" + note,
                         "new id": created.get("id")})
        else:
            rows.append({"agent": full.get("name"), "src version": full.get("version"),
                         "new version": None, "status": f"❌ {tgt_api.last_error or 'failed'}", "new id": None})
    return agent_map, rows


st.subheader("4) Agents")
st.caption(f"{len(plan['agents'])} agent(s) referenced by the setup's workflows will be copied fresh.")
if st.button("Copy agents", key="ootb_s_agents", disabled=agents_blocked):
    with st.spinner("Copying agents…"):
        amap, rows = _copy_agents()
    st.session_state["ootb_agent_map"] = amap
    st.session_state["ootb_res_agents"] = rows
    st.rerun()
if st.session_state.get("ootb_res_agents") is not None:
    _result_table(st.session_state["ootb_res_agents"])
    st.caption(f"Agent id map: {len(st.session_state.get('ootb_agent_map', {}))} agent(s) mapped.")

agent_map = st.session_state.get("ootb_agent_map")


# ----- 5. Agentic workflows -----
def _wf_agent_diag(wf, agent_map):
    """Per-workflow: agent UUIDs found in workflowConfiguration and whether they were copied."""
    config = wf.get("workflowConfiguration") or {}
    config_uuids = _find_uuids(config)
    idx = {a["id"]: a for a in plan.get("src_agent_index", []) if a.get("id")}
    known, unknown = [], []
    for u in sorted(config_uuids):
        if u in idx:
            a = idx[u]
            known.append({
                "agent": a.get("name"), "version": a.get("version"), "source id": u,
                "copied?": ("✅ " + str(agent_map.get(u))) if u in agent_map else "❌ NOT COPIED",
            })
        else:
            unknown.append(u)
    return known, unknown


def _copy_workflows(project_map, agent_map):
    rows = []
    for wf in plan["workflows"]:
        body = _sanitize(wf, WORKFLOW_STRIP)
        if agent_map:
            body["workflowConfiguration"] = _rewrite_uuids(body.get("workflowConfiguration") or {}, agent_map)
        if "projects" in body:
            body["projects"] = _remap_project_ref(body.get("projects"), project_map or {})
        if "trainingProjects" in body:
            body["trainingProjects"] = _remap_project_ref(body.get("trainingProjects"), project_map or {})
        if body.get("trainingCompanyId"):
            body["trainingCompanyId"] = tgt_company.get("id")
        created = tgt_api.create_agent_workflow(body)
        rows.append({
            "workflow": wf.get("name"),
            "status": "✅ created" if created else f"❌ {tgt_api.last_error or 'failed'}",
            "new id": created.get("id") if created else None,
        })
    return rows


st.subheader("5) Agentic workflows")
if not agent_map:
    st.info("Copy the agents first (step 4) — workflow agent references are remapped via the agent id map.")
elif not plan["workflows"]:
    st.caption("No agentic workflows in this setup.")
else:
    with st.expander("Agent-reference check (why a workflow can fail)", expanded=True):
        any_unmapped = False
        for wf in plan["workflows"]:
            known, unknown = _wf_agent_diag(wf, agent_map)
            st.markdown(f"**{wf.get('name')}** — {len(known)} known agent reference(s), {len(unknown)} other UUID(s) in config")
            if known:
                _result_table(known)
                if any("NOT COPIED" in str(r["copied?"]) for r in known):
                    any_unmapped = True
            if unknown:
                st.caption(
                    f"{len(unknown)} UUID(s) in the config are not in the template agent list. These are "
                    "usually workflow node ids, but if the API reports one as a missing agent it means the "
                    "workflow references an agent that `/agents` does not return (e.g. a global/OOTB agent). "
                    "Sample: " + ", ".join(f"`{u}`" for u in unknown[:8])
                )
        if any_unmapped:
            st.error(
                "Some referenced agents were NOT copied — creating the workflow will fail with "
                "'agent not found'. Re-run step 4, or investigate the pre-flight resolution."
            )

    if st.button("Copy agentic workflows", key="ootb_s_workflows", disabled=agents_blocked):
        with st.spinner("Creating agentic workflows…"):
            st.session_state["ootb_res_workflows"] = _copy_workflows(project_map, agent_map)
        st.rerun()
    if st.session_state.get("ootb_res_workflows") is not None:
        rows = st.session_state["ootb_res_workflows"]
        _result_table(rows)
        for r in rows:
            if str(r.get("status", "")).startswith("❌"):
                st.error(f"**{r['workflow']}** failed — full API response:")
                st.code(str(r["status"])[2:].strip(), language="text")
