import re
import streamlit as st
import pandas as pd
from auth import HypatosAPI
from setup_api import SetupAPI
from helpers import check_admin_access
from config import BASE_URL_EU, BASE_URL_US

st.set_page_config(page_title="Copy Agent Workflow", layout="wide")
st.title("Copy Agent Workflow")

#if not check_admin_access():
#    st.stop()

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
            "caw_workflows", "caw_wf_detail",
            "caw_copy_done", "caw_agents_done", "caw_update_results",
        ]:
            st.session_state.pop(key, None)
        st.rerun()

# ---------------------------------------------------------------------------
# Step 4 – Copy agent workflow
# ---------------------------------------------------------------------------
st.header("Step 4: Copy Agent Workflow")

setup_api = SetupAPI(st.session_state["caw_setup_token"])
source_company_id = st.session_state["caw_source_company"].get("id")
target_company_id = st.session_state["caw_target_company"].get("id")

# ── 4a: Load & select workflow ──────────────────────────────────────────────
st.subheader("4a. Select Prompting-Settings Workflow")

if "caw_workflows" not in st.session_state:
    if st.button("Load Source Workflows", key="caw_load_wf"):
        with st.spinner("Fetching agentic workflows…"):
            data = setup_api.get_prompting_settings(source_company_id)
        if data is None:
            st.error(f"Failed to load workflows. {setup_api.last_error or ''}")
        else:
            wfs = data if isinstance(data, list) else data.get("data", [])
            st.session_state["caw_workflows"] = [w for w in wfs if w.get("id")]
            st.rerun()
    st.stop()

workflows = st.session_state["caw_workflows"]
if not workflows:
    st.warning("No workflows found for the source company.")
    if st.button("Reload Workflows", key="caw_reload_wf"):
        st.session_state.pop("caw_workflows", None)
        st.rerun()
    st.stop()

wf_map = {f"{w.get('name', 'Unnamed')} ({w['id']})": w for w in workflows}
selected_label = st.selectbox("Workflow", list(wf_map.keys()), key="caw_wf_sel")
selected_wf = wf_map[selected_label]

if "caw_wf_detail" not in st.session_state:
    if st.button("Confirm & Load Details", key="caw_confirm_wf"):
        with st.spinner("Loading workflow detail…"):
            detail = setup_api.get_prompting_setting_by_id(selected_wf["id"])
        if detail is None:
            st.error(f"Failed to load workflow detail. {setup_api.last_error or ''}")
        else:
            st.session_state["caw_wf_detail"] = detail
            st.rerun()
    st.stop()

wf_detail = st.session_state["caw_wf_detail"]
st.success(
    f"Workflow: **{wf_detail.get('name', selected_wf.get('name', 'Unknown'))}** "
    f"(`{wf_detail.get('id', selected_wf['id'])}`)"
)
with st.expander("Workflow details"):
    st.json(wf_detail)

# ── 4b: Copy workflow to target ─────────────────────────────────────────────
st.subheader("4b. Copy Workflow to Target Company")

if "caw_copy_done" not in st.session_state:
    wf_id = wf_detail.get("id") or selected_wf["id"]
    st.write(
        f"Copy workflow `{wf_id}` → target company `{target_company_id}`"
    )
    if st.button("Copy Workflow", key="caw_do_copy"):
        with st.spinner("Copying workflow…"):
            result = setup_api.copy_workflow(wf_id, target_company_id)
        if result is None:
            st.error(f"Copy failed. {setup_api.last_error or ''}")
        else:
            st.session_state["caw_copy_done"] = result
            st.rerun()
    st.stop()

st.success("Workflow copied to target company.")
with st.expander("Copy response"):
    st.json(st.session_state["caw_copy_done"])

# ── 4c: Update agent prompts in target company ──────────────────────────────
st.subheader("4c. Update Agent Prompts in Target Company")

if "caw_agents_done" not in st.session_state:
    st.write(
        f"Fetches all agents for target company `{target_company_id}`, replaces "
        f"any occurrence of source company ID `{source_company_id}` in prompts "
        "(matched via `(_)[a-fA-F0-9]{24}`), "
        "increments the agent version, then PUTs each agent back."
    )
    if st.button("Fetch Agents & Update Prompts", key="caw_update_agents"):
        with st.spinner("Fetching target company agents…"):
            agents_list = setup_api.get_agents(target_company_id)
        if not agents_list:
            st.error(f"No agents found or fetch failed. {setup_api.last_error or ''}")
        else:
            agent_ids = [a.get("id") for a in agents_list if a.get("id")]
            # Group 1 captures the leading "_" so we can preserve it in the replacement
            pattern = re.compile(r'(_)[a-fA-F0-9]{24}', re.MULTILINE)
            results = []
            progress_bar = st.progress(0)
            total = len(agent_ids)

            for i, agent_id in enumerate(agent_ids):
                # Fetch all versions; latest is the first element
                versions = setup_api.get_agent_by_id(agent_id)
                if not versions:
                    results.append({
                        "agent": agent_id,
                        "id": agent_id,
                        "version": "-",
                        "replacements": "",
                        "status": f"FAILED: could not fetch versions. {setup_api.last_error or ''}",
                    })
                    progress_bar.progress((i + 1) / total)
                    continue

                agent = versions[0]
                prompt = agent.get("prompt") or ""

                # Collect which IDs will be replaced before doing the substitution
                found_ids = {m.group(0)[1:] for m in pattern.finditer(prompt)}
                replaced_ids = [fid for fid in found_ids if fid == source_company_id]
                replacements_label = (
                    ", ".join(f"_{fid} → _{target_company_id}" for fid in replaced_ids)
                    if replaced_ids else "none"
                )

                new_prompt = pattern.sub(
                    lambda m: m.group(1) + target_company_id if m.group(0)[1:] == source_company_id else m.group(0),
                    prompt,
                )

                version_str = str(agent.get("version", "1.0"))
                try:
                    new_version = str(int(float(version_str)) + 1)
                except (ValueError, TypeError):
                    new_version = "2"

                # Strip only server-managed timestamps; id and companyId must be included
                read_only_fields = {"createdAt", "updatedAt"}
                payload = {
                    k: v for k, v in agent.items() if k not in read_only_fields
                }
                payload["prompt"] = new_prompt
                payload["version"] = new_version

                update_result = setup_api.update_agent(agent_id, payload)
                if update_result is not None:
                    results.append({
                        "agent": agent.get("name", agent_id),
                        "id": agent_id,
                        "sent_version": new_version,
                        "replacements": replacements_label,
                        "status": "OK",
                        "payload": payload,
                        "api_response": update_result,
                    })
                else:
                    results.append({
                        "agent": agent.get("name", agent_id),
                        "id": agent_id,
                        "sent_version": new_version,
                        "replacements": replacements_label,
                        "status": f"FAILED: {setup_api.last_error or 'unknown error'}",
                        "payload": payload,
                        "api_response": None,
                    })

                progress_bar.progress((i + 1) / total)

            st.session_state["caw_agents_done"] = True
            st.session_state["caw_update_results"] = results
            st.rerun()
    st.stop()

update_results = st.session_state.get("caw_update_results", [])
failed = [r for r in update_results if not r["status"].startswith("OK")]
if failed:
    st.warning(f"Completed with {len(failed)} failure(s).")
else:
    st.success(f"All {len(update_results)} agent(s) updated successfully.")

for r in update_results:
    icon = "✅" if r["status"] == "OK" else "❌"
    label = f"{icon} **{r['agent']}** — version sent: `{r['sent_version']}` — replacements: {r['replacements']} — {r['status']}"
    with st.expander(label, expanded=r["status"] != "OK"):
        st.write("**Payload sent:**")
        st.json(r["payload"])
        st.write("**API response:**")
        if r["api_response"] is not None:
            st.json(r["api_response"])
        else:
            st.write("_(no response body)_")

if st.button("Reset Step 4", key="caw_reset_step4"):
    for key in ["caw_workflows", "caw_wf_detail", "caw_copy_done",
                "caw_agents_done", "caw_update_results"]:
        st.session_state.pop(key, None)
    st.rerun()
