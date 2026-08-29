import streamlit as st
import pandas as pd

from auth import HypatosAPI
from config import BASE_URL_EU, BASE_URL_US

st.set_page_config(page_title="Copy Composite Enrichment Workflow", layout="wide")
st.title("Copy Composite Enrichment Workflow")
st.caption(
    "Copies composite enrichment workflow definitions between companies — or duplicates "
    "them inside one company — via the /enrichment-workflows REST API. "
    "A workflow definition is a YAML document; project bindings are company-specific and "
    "are handled separately."
)

# Server-managed fields the create/update payloads must not carry.
PAYLOAD_FIELDS = ("name", "definition", "description", "projectIds")


def _reset(prefix: str = "cew_"):
    for key in list(st.session_state.keys()):
        if key.startswith(prefix):
            st.session_state.pop(key, None)


def _payload(workflow: dict) -> dict:
    """Reduce a workflow to the fields POST / PUT accept."""
    out = {}
    for field in PAYLOAD_FIELDS:
        value = workflow.get(field)
        if value is not None:
            out[field] = value
    return out


def _meta_row(workflow: dict) -> dict:
    definition = workflow.get("definition") or ""
    return {
        "name": workflow.get("name"),
        "description": workflow.get("description") or "",
        "version": workflow.get("versionString") or workflow.get("version"),
        "projects": len(workflow.get("projectIds") or []),
        "definition lines": len(definition.splitlines()),
        "updated": workflow.get("updatedAt"),
        "id": workflow.get("id"),
    }


col_head_l, col_head_r = st.columns([5, 1])
with col_head_r:
    if st.button("Reset", key="cew_reset"):
        _reset()
        st.rerun()


# ---------------------------------------------------------------------------
# Step 1 — Credentials
# ---------------------------------------------------------------------------
st.header("Step 1: Credentials")
st.markdown(
    "Standard OAuth2 client credentials. Required scopes: "
    "`enrichment-workflows.read` on the source, `enrichment-workflows.write` on the "
    "target, plus `projects.read` if you want to re-map project bindings by name."
)

col_src, col_tgt = st.columns(2)
with col_src:
    st.subheader("Source Company")
    src_env = st.selectbox(
        "Region",
        (BASE_URL_EU, BASE_URL_US),
        key="cew_src_env",
        format_func=lambda u: "EU" if u == BASE_URL_EU else "US",
    )
    src_id = st.text_input("Source client_id", key="cew_src_id")
    src_secret = st.text_input("Source client_secret", type="password", key="cew_src_secret")

with col_tgt:
    st.subheader("Target Company")
    same_company_choice = st.checkbox(
        "Same as source (duplicate within one company)",
        key="cew_same_company",
    )
    if same_company_choice:
        st.info("Target will reuse the source credentials.")
        tgt_env, tgt_id, tgt_secret = src_env, src_id, src_secret
    else:
        tgt_env = st.selectbox(
            "Region",
            (BASE_URL_EU, BASE_URL_US),
            key="cew_tgt_env",
            format_func=lambda u: "EU" if u == BASE_URL_EU else "US",
        )
        tgt_id = st.text_input("Target client_id", key="cew_tgt_id")
        tgt_secret = st.text_input("Target client_secret", type="password", key="cew_tgt_secret")

if not st.session_state.get("cew_authed"):
    if st.button("Authenticate", key="cew_do_auth"):
        if not (src_id and src_secret and tgt_id and tgt_secret):
            st.error("Please fill in client_id and client_secret for source and target.")
        else:
            src_api = HypatosAPI(src_id.strip(), src_secret.strip(), src_env)
            if not src_api.authenticate():
                st.error(f"Source authentication failed. {src_api.last_error or ''}")
                st.stop()
            src_company = src_api.get_company()
            if not src_company:
                st.error(f"Source authenticated but could not fetch company. {src_api.last_error or ''}")
                st.stop()

            if same_company_choice:
                tgt_api, tgt_company = src_api, src_company
            else:
                tgt_api = HypatosAPI(tgt_id.strip(), tgt_secret.strip(), tgt_env)
                if not tgt_api.authenticate():
                    st.error(f"Target authentication failed. {tgt_api.last_error or ''}")
                    st.stop()
                tgt_company = tgt_api.get_company()
                if not tgt_company:
                    st.error(f"Target authenticated but could not fetch company. {tgt_api.last_error or ''}")
                    st.stop()

            st.session_state["cew_src_api"] = src_api
            st.session_state["cew_tgt_api"] = tgt_api
            st.session_state["cew_src_company"] = src_company
            st.session_state["cew_tgt_company"] = tgt_company
            st.session_state["cew_authed"] = True
            st.rerun()
    st.stop()

src_api: HypatosAPI = st.session_state["cew_src_api"]
tgt_api: HypatosAPI = st.session_state["cew_tgt_api"]
src_company = st.session_state["cew_src_company"]
tgt_company = st.session_state["cew_tgt_company"]
same_company = src_company.get("id") == tgt_company.get("id")

st.success(
    f"Source: **{src_company.get('name', '?')}** (`{src_company.get('id', '?')}`) → "
    f"Target: **{tgt_company.get('name', '?')}** (`{tgt_company.get('id', '?')}`)"
    + ("  ·  *same-company duplicate*" if same_company else "")
)


# ---------------------------------------------------------------------------
# Step 2 — Select source workflows
# ---------------------------------------------------------------------------
st.header("Step 2: Select workflows to copy")

if "cew_src_workflows" not in st.session_state:
    if st.button("Load workflows", key="cew_load"):
        with st.spinner("Fetching enrichment workflows…"):
            src_workflows = src_api.list_enrichment_workflows()
            if not src_workflows:
                st.error(
                    "No enrichment workflows found on the source, or the fetch failed. "
                    + (src_api.last_error or "")
                )
                st.stop()
            tgt_workflows = tgt_api.list_enrichment_workflows() if not same_company else src_workflows
            st.session_state["cew_src_workflows"] = src_workflows
            st.session_state["cew_tgt_workflows"] = tgt_workflows
        st.rerun()
    st.stop()

src_workflows = st.session_state["cew_src_workflows"]
tgt_workflows = st.session_state["cew_tgt_workflows"]
tgt_by_name = {w.get("name"): w for w in tgt_workflows if w.get("name")}

col_l, col_r = st.columns([5, 1])
with col_l:
    st.caption(
        f"{len(src_workflows)} workflow(s) on the source · {len(tgt_by_name)} on the target."
    )
with col_r:
    if st.button("Reload", key="cew_reload"):
        for key in ("cew_src_workflows", "cew_tgt_workflows"):
            st.session_state.pop(key, None)
        st.rerun()

st.dataframe(pd.DataFrame([_meta_row(w) for w in src_workflows]), width="stretch", hide_index=True)

wf_options = [(w.get("id"), w.get("name") or "(unnamed)") for w in src_workflows if w.get("id")]
wf_options.sort(key=lambda x: (x[1] or "").lower())
selected = st.multiselect(
    "Workflows to copy",
    wf_options,
    format_func=lambda x: x[1],
    key="cew_selected",
)

if not selected:
    st.info("Select at least one workflow.")
    st.stop()

src_by_id = {w.get("id"): w for w in src_workflows}

for wid, wname in selected:
    with st.expander(f"YAML definition · {wname}"):
        st.code(src_by_id.get(wid, {}).get("definition") or "(empty)", language="yaml")


# ---------------------------------------------------------------------------
# Step 3 — Options
# ---------------------------------------------------------------------------
st.header("Step 3: Options")

col_name, col_proj = st.columns(2)

with col_name:
    st.subheader("Naming")
    name_suffix = st.text_input(
        "Suffix appended to the copied name",
        value=" (copy)" if same_company else "",
        key="cew_suffix",
        help="A same-company duplicate needs a distinct name; across companies you can keep the original.",
    )
    conflict_mode = st.radio(
        "If the target already has a workflow with that name",
        (
            "Skip it",
            "Overwrite the existing workflow (PUT)",
            "Create a second one with the same name",
        ),
        key="cew_conflict",
    )

with col_proj:
    st.subheader("Project bindings")
    st.caption(
        "`projectIds` reference projects of the *source* company, so they are meaningless "
        "in another company."
    )
    binding_options = ["Do not bind to any project", "Match target projects by name"]
    if same_company:
        binding_options.insert(0, "Keep the source project bindings")
    binding_mode = st.radio("How to handle projectIds", binding_options, key="cew_binding")

project_map = {}
if binding_mode == "Match target projects by name":
    if "cew_project_map" not in st.session_state:
        with st.spinner("Loading projects on both sides…"):
            src_projects = (src_api.get_projects() or {}).get("data", [])
            tgt_projects = (tgt_api.get_projects() or {}).get("data", [])
            tgt_ids_by_name = {p.get("name"): p.get("id") for p in tgt_projects if p.get("name")}
            st.session_state["cew_project_map"] = {
                p.get("id"): tgt_ids_by_name.get(p.get("name"))
                for p in src_projects
                if p.get("id")
            }
            st.session_state["cew_project_names"] = {
                p.get("id"): p.get("name") for p in src_projects if p.get("id")
            }
    project_map = st.session_state["cew_project_map"]


def _resolve_projects(workflow: dict):
    """Return (projectIds for the target, list of source project ids that could not be mapped)."""
    source_ids = workflow.get("projectIds") or []
    if binding_mode == "Keep the source project bindings":
        return list(source_ids), []
    if binding_mode == "Do not bind to any project":
        return [], []
    mapped, unmapped = [], []
    for pid in source_ids:
        target_pid = project_map.get(pid)
        if target_pid:
            mapped.append(target_pid)
        else:
            unmapped.append(pid)
    return mapped, unmapped


# ---------------------------------------------------------------------------
# Step 4 — Preview
# ---------------------------------------------------------------------------
st.header("Step 4: Preview")

plan = []
unmapped_project_ids = set()
for wid, wname in selected:
    source_wf = src_by_id.get(wid, {})
    new_name = f"{source_wf.get('name') or wname}{name_suffix}"
    existing = tgt_by_name.get(new_name)
    project_ids, unmapped = _resolve_projects(source_wf)
    unmapped_project_ids.update(unmapped)

    if existing and conflict_mode == "Skip it":
        action = "skip (name exists)"
    elif existing and conflict_mode.startswith("Overwrite"):
        action = f"overwrite `{existing.get('id')}`"
    else:
        action = "create"

    plan.append(
        {
            "source": source_wf.get("name"),
            "target name": new_name,
            "action": action,
            "projects": len(project_ids),
            "unmapped projects": len(unmapped),
            "source_id": wid,
            "target_id": existing.get("id") if existing else None,
            "payload": {**_payload(source_wf), "name": new_name, "projectIds": project_ids},
        }
    )

st.dataframe(
    pd.DataFrame([{k: v for k, v in row.items() if k not in ("payload", "source_id", "target_id")} for row in plan]),
    width="stretch",
    hide_index=True,
)

if unmapped_project_ids:
    names = st.session_state.get("cew_project_names", {})
    st.warning(
        f"{len(unmapped_project_ids)} source project(s) have no same-named project in the "
        "target — those bindings are dropped: "
        + ", ".join(sorted(names.get(pid, pid) for pid in unmapped_project_ids))
    )

if same_company and not name_suffix.strip():
    st.warning(
        "Duplicating inside one company without a suffix will create a second workflow with "
        "an identical name."
    )

overwrites = [row for row in plan if row["action"].startswith("overwrite")]
if overwrites:
    st.warning(
        "These target workflows will be **replaced** (PUT replaces name, definition, "
        "description and projectIds): " + ", ".join(row["target name"] for row in overwrites)
    )
    confirm = st.checkbox("I understand — overwrite them", key="cew_confirm_overwrite")
else:
    confirm = True


# ---------------------------------------------------------------------------
# Step 5 — Copy
# ---------------------------------------------------------------------------
st.header("Step 5: Copy")

if st.button("Copy workflows", type="primary", key="cew_run", disabled=not confirm):
    results = []
    progress = st.progress(0.0)
    for i, row in enumerate(plan, start=1):
        if row["action"].startswith("skip"):
            results.append({"workflow": row["target name"], "result": "skipped (name exists)"})
        else:
            # Re-fetch the source definition so we never copy a stale cached YAML.
            fresh = src_api.get_enrichment_workflow(row["source_id"])
            if not fresh:
                results.append(
                    {"workflow": row["target name"], "result": f"❌ source fetch failed: {src_api.last_error or ''}"}
                )
                progress.progress(i / len(plan))
                continue
            payload = {**row["payload"], "definition": fresh.get("definition")}

            if row["action"].startswith("overwrite"):
                created = tgt_api.update_enrichment_workflow(row["target_id"], payload)
            else:
                created = tgt_api.create_enrichment_workflow(payload)

            if created:
                results.append(
                    {
                        "workflow": row["target name"],
                        "result": "✅ " + ("overwritten" if row["action"].startswith("overwrite") else "created"),
                        "new id": created.get("id"),
                    }
                )
            else:
                results.append({"workflow": row["target name"], "result": f"❌ {tgt_api.last_error or 'failed'}"})
        progress.progress(i / len(plan))

    st.dataframe(pd.DataFrame(results), width="stretch", hide_index=True)
    failed = [r for r in results if str(r["result"]).startswith("❌")]
    if failed:
        st.error(f"{len(failed)} workflow(s) failed.")
    else:
        st.success("Done.")
    # The cached target list is stale now — refresh it so Step 4 keeps showing
    # accurate conflict detection without forcing a full reload.
    refreshed = tgt_api.list_enrichment_workflows()
    if refreshed:
        st.session_state["cew_tgt_workflows"] = refreshed
        if same_company:
            st.session_state["cew_src_workflows"] = refreshed
