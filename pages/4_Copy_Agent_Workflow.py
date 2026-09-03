import re
import json
import streamlit as st
import pandas as pd
from auth import HypatosAPI
from config import BASE_URL_EU, BASE_URL_US

st.set_page_config(page_title="Copy Agent Workflow", layout="wide")
st.title("Copy Agent Workflow")
st.caption(
    "Copies an agent workflow (and optionally the agents it references) between "
    "companies via the Agent Management REST API — or duplicates one within the same company."
)


# Provenance / server-managed fields that must be stripped before POST.
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

UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _sanitize(obj: dict, strip_keys: set) -> dict:
    return {k: v for k, v in obj.items() if k not in strip_keys}


def _find_uuids(node) -> set:
    """Recursively collect UUID-looking strings anywhere in a nested structure."""
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


def _rewrite_uuids(node, mapping: dict):
    """Return a deep copy with any UUID string in `mapping` swapped for its replacement."""
    if isinstance(node, dict):
        return {k: _rewrite_uuids(v, mapping) for k, v in node.items()}
    if isinstance(node, list):
        return [_rewrite_uuids(v, mapping) for v in node]
    if isinstance(node, str) and node in mapping:
        return mapping[node]
    if isinstance(node, str):
        # also handle substrings — replace each occurrence
        out = node
        for src, dst in mapping.items():
            if src in out:
                out = out.replace(src, dst)
        return out
    return node


def _reset(prefix: str):
    for key in list(st.session_state.keys()):
        if key.startswith(prefix):
            st.session_state.pop(key, None)


# ---------------------------------------------------------------------------
# Step 1 — Credentials
# ---------------------------------------------------------------------------
st.header("Step 1: Credentials")

col1, col2 = st.columns([5, 1])
with col2:
    if st.button("Reset", key="caw_reset_all"):
        _reset("caw_")
        st.rerun()

st.markdown(
    "The Agent Management API uses standard OAuth2 client credentials. "
    "Enter the source company credentials, and either identical credentials for the target "
    "or check *Same as source* to duplicate within one company."
)

col_src, col_tgt = st.columns(2)
with col_src:
    st.subheader("Source Company")
    src_env = st.selectbox(
        "Region",
        (BASE_URL_EU, BASE_URL_US),
        key="caw_src_env",
        format_func=lambda u: "EU" if u == BASE_URL_EU else "US",
    )
    src_id = st.text_input("Source client_id", key="caw_src_id")
    src_secret = st.text_input("Source client_secret", type="password", key="caw_src_secret")

with col_tgt:
    st.subheader("Target Company")
    same_company = st.checkbox(
        "Same as source (copy within one company)",
        key="caw_same_company",
    )
    if same_company:
        st.info("Target will reuse the source credentials.")
        tgt_env = src_env
        tgt_id = src_id
        tgt_secret = src_secret
    else:
        tgt_env = st.selectbox(
            "Region",
            (BASE_URL_EU, BASE_URL_US),
            key="caw_tgt_env",
            format_func=lambda u: "EU" if u == BASE_URL_EU else "US",
        )
        tgt_id = st.text_input("Target client_id", key="caw_tgt_id")
        tgt_secret = st.text_input("Target client_secret", type="password", key="caw_tgt_secret")

if not st.session_state.get("caw_authed"):
    if st.button("Authenticate", key="caw_do_auth"):
        if not (src_id and src_secret and tgt_id and tgt_secret):
            st.error("Please fill in both client_id and client_secret for source and target.")
        else:
            src_api = HypatosAPI(src_id.strip(), src_secret.strip(), src_env)
            if not src_api.authenticate():
                st.error(f"Source authentication failed. {src_api.last_error or ''}")
                st.stop()
            src_company = src_api.get_company()
            if not src_company:
                st.error(f"Source authenticated but could not fetch company. {src_api.last_error or ''}")
                st.stop()

            if same_company:
                tgt_api = src_api
                tgt_company = src_company
            else:
                tgt_api = HypatosAPI(tgt_id.strip(), tgt_secret.strip(), tgt_env)
                if not tgt_api.authenticate():
                    st.error(f"Target authentication failed. {tgt_api.last_error or ''}")
                    st.stop()
                tgt_company = tgt_api.get_company()
                if not tgt_company:
                    st.error(f"Target authenticated but could not fetch company. {tgt_api.last_error or ''}")
                    st.stop()

            st.session_state["caw_source_auth"] = src_api
            st.session_state["caw_source_company"] = src_company
            st.session_state["caw_target_auth"] = tgt_api
            st.session_state["caw_target_company"] = tgt_company
            st.session_state["caw_authed"] = True
            st.rerun()
    st.stop()

src_company = st.session_state["caw_source_company"]
tgt_company = st.session_state["caw_target_company"]
src_api: HypatosAPI = st.session_state["caw_source_auth"]
tgt_api: HypatosAPI = st.session_state["caw_target_auth"]
same_company = src_company.get("id") == tgt_company.get("id")

st.success(
    f"Source: **{src_company.get('name', '?')}** (`{src_company.get('id', '?')}`) → "
    f"Target: **{tgt_company.get('name', '?')}** (`{tgt_company.get('id', '?')}`)"
    + ("  ·  *same-company copy*" if same_company else "")
)

# ---------------------------------------------------------------------------
# Step 2 — Choose what to copy
# ---------------------------------------------------------------------------
st.header("Step 2: What do you want to copy?")

mode = st.radio(
    "Copy mode",
    ["Agent Workflow (with referenced agents)", "Agents only"],
    key="caw_mode",
    horizontal=True,
)

target_company_id = tgt_company.get("id")


# Always-available base model to fall back to when the agent's own model is not
# active in the target company (create_agent -> 422 "Model is not active ...").
BASE_MODEL_ID = "3548e0ca-e5e4-4c1a-8ca2-a0878036053e"


def _is_model_inactive(err: str) -> bool:
    """True when create_agent failed because the agent's model is not active in the target."""
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


def _post_agent(agent_body: dict, override_name: str = None, override_version: str = None):
    """Sanitize + POST an agent to the target company.
    Returns (created_agent, error_str, payload, note). On a 422 'model not active'
    error the agent's model is swapped for BASE_MODEL_ID and the create is retried,
    so one dead model reference does not break the whole copy."""
    payload = _sanitize(agent_body, AGENT_STRIP)
    if override_name is not None:
        payload["name"] = override_name
    if override_version is not None:
        payload["version"] = override_version
    # Ensure required-null-ok fields survive as-is; drop obviously empty version to let API assign one
    if not payload.get("version"):
        payload.pop("version", None)
    created = tgt_api.create_agent(payload)
    note = None
    if created is None and _is_model_inactive(tgt_api.last_error):
        _set_model(payload, BASE_MODEL_ID)
        retried = tgt_api.create_agent(payload)
        if retried is not None:
            created = retried
            note = f"model not active in target — reassigned to base model {BASE_MODEL_ID}"
    return created, (tgt_api.last_error if created is None else None), payload, note


def _post_workflow(workflow_body: dict, override_name: str = None, drop_projects: bool = False):
    payload = _sanitize(workflow_body, WORKFLOW_STRIP)
    if override_name is not None:
        payload["name"] = override_name
    if drop_projects:
        # Cross-company: source-company project ids do not exist in the target.
        # `projects` is a required field, so send an empty string to satisfy the
        # schema without binding the workflow to any projects; user assigns later.
        payload["projects"] = ""
        payload.pop("trainingProjects", None)
        payload.pop("trainingCompanyId", None)
    created = tgt_api.create_agent_workflow(payload)
    return created, (tgt_api.last_error if created is None else None), payload


# ---------------------------------------------------------------------------
# Mode A — Agent Workflow copy
# ---------------------------------------------------------------------------
if mode.startswith("Agent Workflow"):
    st.subheader("2a. Select source workflow")

    if "caw_workflows" not in st.session_state:
        if st.button("Load source workflows", key="caw_load_workflows"):
            with st.spinner("Fetching agent workflows…"):
                wfs = src_api.list_agent_workflows()
            if not wfs:
                st.error(f"No workflows found or fetch failed. {src_api.last_error or ''}")
                st.stop()
            st.session_state["caw_workflows"] = wfs
            st.rerun()
        st.stop()

    workflows = st.session_state["caw_workflows"]
    wf_labels = {
        f"{w.get('name', 'Unnamed')} · v{w.get('version', '?')} "
        f"({w.get('id', '?')[:8]}…)": w
        for w in workflows if w.get("id")
    }
    selected_label = st.selectbox("Workflow", list(wf_labels.keys()), key="caw_wf_sel")
    selected_wf = wf_labels[selected_label]

    if st.button("Load workflow detail", key="caw_load_wf_detail"):
        with st.spinner("Fetching workflow detail…"):
            detail = src_api.get_agent_workflow(selected_wf["id"])
        if detail is None:
            st.error(f"Failed to load workflow. {src_api.last_error or ''}")
            st.stop()
        st.session_state["caw_wf_detail"] = detail
        # Also refresh source + target agent lists at the same time
        with st.spinner("Fetching source & target agents…"):
            st.session_state["caw_src_agents"] = src_api.list_agents()
            st.session_state["caw_tgt_agents"] = tgt_api.list_agents() if not same_company else st.session_state["caw_src_agents"]
        st.rerun()

    if "caw_wf_detail" not in st.session_state:
        st.stop()

    wf_detail = st.session_state["caw_wf_detail"]
    src_agents = st.session_state.get("caw_src_agents", [])
    tgt_agents = st.session_state.get("caw_tgt_agents", [])

    with st.expander("Source workflow detail"):
        st.json(wf_detail)

    # Identify agents referenced by the workflow configuration.
    # Workflow configs may point at agents either by UUID (id) or by "name:version"
    # string, so we scan for both and merge.
    wf_config = wf_detail.get("workflowConfiguration") or {}
    referenced_uuids = _find_uuids(wf_config)
    src_by_id = {a.get("id"): a for a in src_agents if a.get("id")}
    by_uuid = [src_by_id[u] for u in referenced_uuids if u in src_by_id]

    config_str = json.dumps(wf_config)
    by_name = []
    seen_ids = {a.get("id") for a in by_uuid}
    for a in src_agents:
        aid = a.get("id")
        if aid in seen_ids:
            continue
        name = (a.get("name") or "").strip()
        version = (a.get("version") or "").strip()
        if not name:
            continue
        # Prefer name:version, then bare quoted name as a fallback.
        needles = []
        if version:
            needles.append(f"{name}:{version}")
        needles.append(f'"{name}"')
        if any(n in config_str for n in needles):
            by_name.append(a)
            seen_ids.add(aid)

    referenced_src_agents = by_uuid + by_name

    st.subheader("2b. Agents referenced by this workflow")
    if not referenced_src_agents and referenced_uuids:
        st.warning(
            f"Found {len(referenced_uuids)} UUID(s) inside the workflow configuration but none "
            "match an agent in the source company. This is fine if the workflow only references "
            "OOTB or shared agents — nothing will be copied on the agent side."
        )
    elif not referenced_uuids:
        st.info("No agent UUIDs detected in workflowConfiguration. Only the workflow will be copied.")

    tgt_key = {(a.get("name"), a.get("version")): a for a in tgt_agents}

    rows = []
    for a in referenced_src_agents:
        key = (a.get("name"), a.get("version"))
        rows.append({
            "name": a.get("name"),
            "version": a.get("version"),
            "type": a.get("type"),
            "source_id": a.get("id"),
            "in_target": key in tgt_key,
            "target_id": tgt_key.get(key, {}).get("id") if key in tgt_key else None,
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    # Diagnostic: UUIDs in the config that do NOT resolve to any source agent.
    unresolved_uuids = sorted(u for u in referenced_uuids if u not in src_by_id)
    if unresolved_uuids:
        with st.expander(f"Unresolved UUIDs in workflowConfiguration ({len(unresolved_uuids)})"):
            st.caption(
                "These UUIDs are not agents in the source company's /agents list. Most are workflow "
                "node ids, but if the copy fails with 'agent not found' and the API names one of "
                "these, the workflow references an agent that /agents does not return (e.g. a "
                "global / OOTB agent) — which cannot be copied by name or id from here."
            )
            st.code("\n".join(unresolved_uuids), language="text")

    if same_company:
        st.info(
            "Same-company copy: referenced agents are reused as-is — only the workflow is duplicated. "
            "You must give the new workflow a distinct name."
        )
        copy_choices = []
    else:
        copy_choices = [
            r for r in rows
            if not r["in_target"]
        ]
        if copy_choices:
            st.markdown(f"**{len(copy_choices)}** agent(s) need to be created in the target.")
        else:
            st.markdown("All referenced agents already exist in the target — only the workflow will be copied.")

    if not same_company:
        st.info(
            "Cross-company copy: the workflow will be created without any project "
            "assignment (source project ids do not exist in the target). Bind it to "
            "the desired target projects afterwards."
        )

    st.subheader("2c. Target workflow name")
    default_wf_name = wf_detail.get("name", "")
    if same_company:
        default_wf_name = f"{default_wf_name} (copy)" if default_wf_name else "workflow (copy)"
    new_wf_name = st.text_input(
        "New workflow name",
        value=default_wf_name,
        key="caw_new_wf_name",
    )

    if same_company and new_wf_name.strip() == (wf_detail.get("name") or "").strip():
        st.warning("Please pick a name different from the source workflow when copying within the same company.")

    if st.button("Execute copy", key="caw_do_copy_wf", type="primary"):
        results = []
        agent_id_map = {}  # source agent id -> target agent id

        # Step 1 — copy missing referenced agents (cross-company only)
        if not same_company and copy_choices:
            progress = st.progress(0.0, text="Copying agents…")
            for i, r in enumerate(copy_choices):
                sid = r["source_id"]
                full = src_api.get_agent(sid)
                if not full:
                    results.append({
                        "kind": "agent", "name": r["name"], "version": r["version"],
                        "status": f"FAILED (fetch): {src_api.last_error or ''}",
                        "payload": None, "response": None,
                    })
                    progress.progress((i + 1) / len(copy_choices))
                    continue
                created, err, payload, note = _post_agent(full)
                if created:
                    agent_id_map[sid] = created.get("id")
                    results.append({
                        "kind": "agent", "name": r["name"], "version": r["version"],
                        "status": "OK" + (f" — {note}" if note else ""),
                        "payload": payload, "response": created,
                    })
                else:
                    results.append({
                        "kind": "agent", "name": r["name"], "version": r["version"],
                        "status": f"FAILED (create): {err or ''}",
                        "payload": payload, "response": None,
                    })
                progress.progress((i + 1) / len(copy_choices))

        # Also carry over agents that already exist in target (name+version) so the workflow
        # config can be rewritten to point at target ids.
        if not same_company:
            for r in rows:
                if r["in_target"] and r["target_id"] and r["source_id"]:
                    agent_id_map[r["source_id"]] = r["target_id"]

        # Step 2 — copy the workflow
        wf_payload_body = dict(wf_detail)
        if agent_id_map:
            wf_payload_body["workflowConfiguration"] = _rewrite_uuids(
                wf_payload_body.get("workflowConfiguration") or {}, agent_id_map
            )
        # projects and trainingProjects reference the source company projects — the target
        # company almost certainly has different project ids, so strip them on cross-company
        # copies (user can bind projects to the workflow manually afterwards).
        with st.spinner("Copying workflow…"):
            created_wf, err_wf, wf_payload = _post_workflow(
                wf_payload_body,
                override_name=new_wf_name.strip() or None,
                drop_projects=not same_company,
            )
        if created_wf:
            results.append({
                "kind": "workflow", "name": wf_payload.get("name"), "version": "-",
                "status": "OK",
                "payload": wf_payload, "response": created_wf,
            })
        else:
            results.append({
                "kind": "workflow", "name": wf_payload.get("name"), "version": "-",
                "status": f"FAILED: {err_wf or ''}",
                "payload": wf_payload, "response": None,
            })

        st.session_state["caw_wf_results"] = results
        st.rerun()

    results = st.session_state.get("caw_wf_results")
    if results:
        st.subheader("Result")
        failed = [r for r in results if not r["status"].startswith("OK")]
        (st.warning if failed else st.success)(
            f"Completed with {len(failed)} failure(s) / {len(results) - len(failed)} success(es)."
        )
        for r in results:
            icon = "✅" if r["status"].startswith("OK") else "❌"
            with st.expander(
                f"{icon} [{r['kind']}] {r['name']} — {r['status']}",
                expanded=not r["status"].startswith("OK"),
            ):
                if not r["status"].startswith("OK"):
                    st.write("**Error (full API response):**")
                    st.code(r["status"], language="text")
                if r["payload"] is not None:
                    st.write("**Payload sent:**")
                    st.json(r["payload"])
                if r["response"] is not None:
                    st.write("**API response:**")
                    st.json(r["response"])

# ---------------------------------------------------------------------------
# Mode B — Agents-only copy
# ---------------------------------------------------------------------------
else:
    st.subheader("2a. Select source agents")

    if "caw_src_agents_only" not in st.session_state:
        if st.button("Load source agents", key="caw_load_src_agents"):
            with st.spinner("Fetching agents…"):
                src_agents = src_api.list_agents()
                tgt_agents = (
                    src_agents if same_company else tgt_api.list_agents()
                )
            if not src_agents:
                st.error(f"No agents found or fetch failed. {src_api.last_error or ''}")
                st.stop()
            st.session_state["caw_src_agents_only"] = src_agents
            st.session_state["caw_tgt_agents_only"] = tgt_agents
            st.rerun()
        st.stop()

    src_agents = st.session_state["caw_src_agents_only"]
    tgt_agents = st.session_state["caw_tgt_agents_only"]
    tgt_key = {(a.get("name"), a.get("version")): a for a in tgt_agents}

    df_rows = []
    for a in src_agents:
        key = (a.get("name"), a.get("version"))
        df_rows.append({
            "name": a.get("name"),
            "version": a.get("version"),
            "type": a.get("type"),
            "isOotb": a.get("isOotb"),
            "in_target": key in tgt_key,
            "source_id": a.get("id"),
        })
    df = pd.DataFrame(df_rows)

    with st.expander("All source agents", expanded=False):
        st.dataframe(df, width="stretch", hide_index=True)

    labels = {
        f"{r['name']} · v{r['version']} "
        f"{'· already in target' if r['in_target'] else ''}": r["source_id"]
        for r in df_rows
    }
    default = [
        lbl for lbl, sid in labels.items()
        if not next((r for r in df_rows if r["source_id"] == sid), {}).get("in_target")
        and not next((r for r in df_rows if r["source_id"] == sid), {}).get("isOotb")
    ]
    picked = st.multiselect(
        "Agents to copy",
        list(labels.keys()),
        default=default if not same_company else [],
        key="caw_agent_pick",
    )
    picked_ids = [labels[p] for p in picked]

    st.subheader("2b. Naming")
    suffix = ""
    if same_company:
        suffix = st.text_input(
            "Name suffix (required for same-company copy)",
            value=" (copy)",
            key="caw_agent_suffix",
            help="Appended to the name of every copied agent to avoid collisions.",
        )

    if st.button("Execute copy", key="caw_do_copy_agents", type="primary"):
        results = []
        if not picked_ids:
            st.info("No agents selected.")
        else:
            progress = st.progress(0.0, text="Copying agents…")
            for i, sid in enumerate(picked_ids):
                full = src_api.get_agent(sid)
                if not full:
                    results.append({
                        "name": sid, "version": "-",
                        "status": f"FAILED (fetch): {src_api.last_error or ''}",
                        "payload": None, "response": None,
                    })
                    progress.progress((i + 1) / len(picked_ids))
                    continue
                override_name = None
                if suffix:
                    override_name = f"{full.get('name', '')}{suffix}"
                created, err, payload, note = _post_agent(full, override_name=override_name)
                if created:
                    results.append({
                        "name": payload.get("name"), "version": payload.get("version", "-"),
                        "status": "OK" + (f" — {note}" if note else ""),
                        "payload": payload, "response": created,
                    })
                else:
                    results.append({
                        "name": payload.get("name"), "version": payload.get("version", "-"),
                        "status": f"FAILED (create): {err or ''}",
                        "payload": payload, "response": None,
                    })
                progress.progress((i + 1) / len(picked_ids))
            st.session_state["caw_agent_results"] = results
            st.rerun()

    results = st.session_state.get("caw_agent_results")
    if results:
        st.subheader("Result")
        failed = [r for r in results if not r["status"].startswith("OK")]
        (st.warning if failed else st.success)(
            f"Completed with {len(failed)} failure(s) / {len(results) - len(failed)} success(es)."
        )
        for r in results:
            icon = "✅" if r["status"].startswith("OK") else "❌"
            with st.expander(
                f"{icon} {r['name']} v{r['version']} — {r['status']}",
                expanded=not r["status"].startswith("OK"),
            ):
                if r["payload"] is not None:
                    st.write("**Payload sent:**")
                    st.json(r["payload"])
                if r["response"] is not None:
                    st.write("**API response:**")
                    st.json(r["response"])
