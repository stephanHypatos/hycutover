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
DEFAULT_SETUPS = {
    "invoice_processing_a": {"label": "Invoice Processing — Setup A", "group": "Invoice Processing", "project_ids": []},
    "invoice_processing_b": {"label": "Invoice Processing — Setup B", "group": "Invoice Processing", "project_ids": []},
    "order_confirmation": {"label": "Order Confirmation", "group": "Order Confirmation", "project_ids": []},
    "order_management": {"label": "Order Management", "group": "Order Management", "project_ids": []},
}


def _load_setups() -> dict:
    """Merge the DEFAULT_SETUPS shape with whatever secrets provide."""
    setups = {k: dict(v) for k, v in DEFAULT_SETUPS.items()}
    try:
        cfg = st.secrets["ootb"]["setups"]
    except Exception:
        return setups
    for key, val in dict(cfg).items():
        base = dict(setups.get(key, {"label": key, "group": "Other", "project_ids": []}))
        base["label"] = val.get("label", base.get("label", key))
        base["group"] = val.get("group", base.get("group", "Other"))
        base["project_ids"] = [str(p) for p in (val.get("project_ids") or [])]
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

if not setup_project_ids:
    st.warning(
        f"**{setup['label']}** has no project ids configured. Add them under "
        f"`[ootb.setups.{setup_key}]` → `project_ids` in secrets.toml."
    )
    st.stop()

st.caption(f"**{setup['label']}** → {len(setup_project_ids)} template project(s).")


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

        # Enrichment workflows bound to the setup projects.
        setup_id_set = set(setup_project_ids)
        enrichment = [
            w for w in src_api.list_enrichment_workflows()
            if setup_id_set & set(w.get("projectIds") or [])
        ]

        # Agent workflows assigned to the setup projects + referenced agents.
        wf_summaries = {}
        for pid in setup_project_ids:
            for w in src_api.list_agent_workflows(project_id=pid):
                if w.get("id"):
                    wf_summaries.setdefault(w["id"], w)
        workflows = []
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
        "enrichment": enrichment,
        "workflows": workflows,
        "agents": agents,
        "agent_collisions": agent_collisions,
        "enrich_collisions": [w.get("name") for w in enrichment if w.get("name") in tgt_enrich_names],
        "model_id": model_id,
        "prefix": name_prefix,
        "suffix": name_suffix,
    }
    st.session_state.pop("ootb_results", None)
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
# Step 5 — Deploy
# ---------------------------------------------------------------------------
st.header("Step 5: Deploy")


def _affix(name: str) -> str:
    return f"{name_prefix or ''}{name or ''}{name_suffix or ''}"


def _deploy():
    results = {"projects": [], "routings": [], "enrichment": [], "agents": [], "workflows": []}
    headers = tgt_api.get_headers()
    create_url = f"{tgt_api.base_url}/projects"
    project_id_map = {}

    # --- 1. Projects ---
    for pid in setup_project_ids:
        name = plan["src_project_names"].get(pid, pid)
        detail = src_api.get_project_by_id(pid)
        schema = src_api.get_project_schema(pid)
        if not (detail and schema):
            results["projects"].append({"project": name, "status": "❌ source fetch failed"})
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
            project_id_map[pid] = new_id
            results["projects"].append({"project": payload["name"], "status": "✅ created", "new id": new_id})
        else:
            results["projects"].append({"project": payload["name"], "status": f"❌ HTTP {resp.status_code}: {resp.text[:200]}"})

    # --- 2. Routing rules (both endpoints in the map) ---
    for rid in src_api.get_all_routing_rule_ids(limit=50):
        rule = src_api.get_routing_by_id(rid)
        if not rule:
            continue
        frm, to = rule.get("fromProjectId"), rule.get("toProjectId")
        if frm not in project_id_map or to not in project_id_map:
            continue
        new_rule = dict(rule)
        new_rule["fromProjectId"] = project_id_map[frm]
        new_rule["toProjectId"] = project_id_map[to]
        for f in ("id", "createdAt", "updatedAt"):
            new_rule.pop(f, None)
        created = tgt_api.create_routing_rule(new_rule)
        route = f"{plan['src_project_names'].get(frm, frm)} → {plan['src_project_names'].get(to, to)}"
        if created:
            results["routings"].append({"route": route, "status": "✅ created", "new id": created.get("id")})
        else:
            results["routings"].append({"route": route, "status": f"❌ {tgt_api.last_error or 'failed'}"})

    # --- 3. Composite enrichment workflows ---
    tgt_enrich_names = {w.get("name") for w in tgt_api.list_enrichment_workflows()}
    for wf in plan["enrichment"]:
        if wf.get("name") in tgt_enrich_names:
            results["enrichment"].append({"workflow": wf.get("name"), "status": "skipped (name exists)"})
            continue
        fresh = src_api.get_enrichment_workflow(wf.get("id")) or wf
        remapped = [project_id_map[p] for p in (fresh.get("projectIds") or []) if p in project_id_map]
        payload = {k: fresh.get(k) for k in ENRICHMENT_FIELDS if fresh.get(k) is not None}
        payload["projectIds"] = remapped
        created = tgt_api.create_enrichment_workflow(payload)
        if created:
            results["enrichment"].append({"workflow": payload["name"], "status": "✅ created", "new id": created.get("id")})
        else:
            results["enrichment"].append({"workflow": payload.get("name"), "status": f"❌ {tgt_api.last_error or 'failed'}"})

    # --- 4. Agents (fresh copies) then agentic workflows ---
    agent_id_map = {}
    for sid, full in plan["agents"].items():
        payload = _sanitize(full, AGENT_STRIP)
        if not payload.get("version"):
            payload.pop("version", None)
        created = tgt_api.create_agent(payload)
        if created:
            agent_id_map[sid] = created.get("id")
            results["agents"].append({"agent": full.get("name"), "version": full.get("version"), "status": "✅ created", "new id": created.get("id")})
        else:
            results["agents"].append({"agent": full.get("name"), "version": full.get("version"), "status": f"❌ {tgt_api.last_error or 'failed'}"})

    for wf in plan["workflows"]:
        body = _sanitize(wf, WORKFLOW_STRIP)
        if agent_id_map:
            body["workflowConfiguration"] = _rewrite_uuids(body.get("workflowConfiguration") or {}, agent_id_map)
        if "projects" in body:
            body["projects"] = _remap_project_ref(body.get("projects"), project_id_map)
        if "trainingProjects" in body:
            body["trainingProjects"] = _remap_project_ref(body.get("trainingProjects"), project_id_map)
        if body.get("trainingCompanyId"):
            body["trainingCompanyId"] = tgt_company.get("id")
        created = tgt_api.create_agent_workflow(body)
        if created:
            results["workflows"].append({"workflow": wf.get("name"), "status": "✅ created", "new id": created.get("id")})
        else:
            results["workflows"].append({"workflow": wf.get("name"), "status": f"❌ {tgt_api.last_error or 'failed'}"})

    return results


if not model_id:
    st.warning("The selected target project has no extraction model id. Pick a different target project in Step 2.")
    deploy_blocked = True

deploy_clicked = st.button(
    "Deploy setup to target company",
    type="primary",
    key="ootb_deploy",
    disabled=deploy_blocked,
)

if deploy_clicked and not deploy_blocked:
    with st.status("Deploying…", expanded=True) as status:
        st.write("Cloning projects, routings, enrichment and agentic workflows…")
        st.session_state["ootb_results"] = _deploy()
        status.update(label="Deploy finished", state="complete")
    st.rerun()

results = st.session_state.get("ootb_results")
if results:
    st.subheader("Result")
    any_fail = False
    for title, key in [
        ("Projects", "projects"),
        ("Routing rules", "routings"),
        ("Composite enrichment workflows", "enrichment"),
        ("Agents", "agents"),
        ("Agentic workflows", "workflows"),
    ]:
        rows = results.get(key) or []
        st.markdown(f"**{title}** ({len(rows)})")
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            any_fail = any_fail or any(str(r.get("status", "")).startswith("❌") for r in rows)
        else:
            st.caption("_none_")
    if any_fail:
        st.error("Some artefacts failed — see the ❌ rows above. Successful ones were still created.")
    else:
        st.success("✅ Deploy completed successfully.")
