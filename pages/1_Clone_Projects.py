import streamlit as st
import requests
from auth import HypatosAPI
from helpers import (
    clear_session_state_generic,
    get_source_base_url,
    get_target_base_url,
    input_credentials,
    validate_scopes,
)
from config import BASE_URL_EU, BASE_URL_US


st.set_page_config(page_title="Clone Projects", page_icon=":cyclone:")

# --- Authentication Section (Always at Top) ---
def authenticate_credentials():
    """Authenticate both source and target credentials and store them separately."""
    source_user = st.session_state.get("sourcecompany_user", "")
    source_pw = st.session_state.get("sourcecompany_apipw", "")
    target_user = st.session_state.get("targetcompany_user", "")
    target_pw = st.session_state.get("targetcompany_apipw", "")
    source_base_url = get_source_base_url()
    target_base_url = get_target_base_url()

    errors = False
    if not source_user or not source_pw:
        st.error("Please provide Source Company credentials.")
        errors = True
    if not target_user or not target_pw:
        st.error("Please provide Target Company credentials.")
        errors = True
    if errors:
        return

    source_auth = HypatosAPI(source_user, source_pw, source_base_url)
    target_auth = HypatosAPI(target_user, target_pw, target_base_url)
    
    if source_auth.authenticate():
        if validate_scopes(source_auth, "Source Company"):
            source_company = source_auth.get_company_info()
            company_name = source_company.get("name", "Unknown") if source_company else "Unknown"
            if source_company:
                st.session_state["source_company_name"] = company_name
                st.info(f"📦 Source Company: **{company_name}**")
            else:
                st.error("Source credentials authenticated, but company details could not be fetched. Please verify the credentials have `companies.read` for the selected API region.")
                st.session_state.pop("source_auth", None)
                return
            st.session_state["source_auth"] = source_auth
            st.success("Source Authentication succeeded!")
        else:
            st.session_state.pop("source_auth", None)
    else:
        error_msg = source_auth.last_error or "Unknown error occurred"
        st.error(f"❌ Source Authentication failed\n\n**Error:** {error_msg}")
    
    if target_auth.authenticate():
        if validate_scopes(target_auth, "Target Company"):
            target_company = target_auth.get_company_info()
            company_name = target_company.get("name", "Unknown") if target_company else "Unknown"
            if target_company:
                st.session_state["target_company_name"] = company_name
                st.info(f"📦 Target Company: **{company_name}**")
            else:
                st.error("Target credentials authenticated, but company details could not be fetched. Please verify the credentials have `companies.read` for the selected API region.")
                st.session_state.pop("target_auth", None)
                return
            st.session_state["target_auth"] = target_auth
            st.success("Target Authentication succeeded!")
        else:
            st.session_state.pop("target_auth", None)
    else:
        error_msg = target_auth.last_error or "Unknown error occurred"
        st.error(f"❌ Target Authentication failed\n\n**Error:** {error_msg}")

# --- Copy Projects Section ---
def copy_projects_section():
    st.title("Copy Projects")
    # Ensure both auth objects exist.
    if "source_auth" not in st.session_state or "target_auth" not in st.session_state:
        st.error("Both source and target authentication must be completed in the top section.")
        return

    source_auth = st.session_state["source_auth"]
    target_auth = st.session_state["target_auth"]
    # When creating projects, we use target_auth (target token) for posting.
    headers = target_auth.get_headers()
    create_project_url = f"{target_auth.base_url}/projects"

    # Retrieve projects from source.
    data = source_auth.get_projects()
    projects = data.get("data", [])
    if not projects:
        st.error("Failed to retrieve projects from the source company.")
        return

    # Retrieve projects from target for model ID selection.
    target_data = target_auth.get_projects()
    target_projects = target_data.get("data", [])
    if not target_projects:
        st.error("Failed to retrieve projects from the target company.")
        return

    st.subheader("New Project Details")
    with st.expander("See explanation for Model ID"):
        st.write('''
            How to find the modelId?

            Select a project from the target company that has the correct model setup. If you don't have one, create a new project in the target company with the following parameters:
            - Choose any "Name" for your Project.
            - In "Model configuration", select "Hypatos AI Agent";
            - In Datapoints, always select "Invoice EU" ( it does not matter anyway, as you will delete the project in next 5 minutes anyway )
            - Click "Next" -> don't change the datapoints structure -> click "Create";
            - Refresh this page and select the project you just created from the dropdown below to get the model ID.
        ''')

    target_project_list = [(proj["id"], proj["name"]) for proj in target_projects]
    selected_target_project = st.selectbox("Select Target Project for Model ID", target_project_list, format_func=lambda x: x[1])
    selected_model_id = None
    if selected_target_project:
        for proj in target_projects:
            if proj["id"] == selected_target_project[0]:
                selected_model_id = proj.get("extractionModelId")
                st.write(f"Selected Model ID: {selected_model_id}")
                break


    project_list = [(proj["id"], proj["name"]) for proj in projects]
    st.subheader("Select Projects to Copy")
    selected_projects = st.multiselect("Projects", project_list, format_func=lambda x: x[1])

    if st.button("Create Project Copies"):
        if not selected_target_project or not selected_model_id:
            st.error("Please select a target project for the model ID.")
            return
        if not selected_projects:
            st.error("Please select at least one project to copy.")
            return

        # Mapping: original project ID -> new project ID
        project_id_map = {}
        project_name_map = {}
        for project_id, project_name in selected_projects:
            project_details = source_auth.get_project_by_id(project_id)
            project_schema = source_auth.get_project_schema(project_id)
            if project_details and project_schema:
                final_project_name = project_name

                new_project_payload = {
                    "name": final_project_name,
                    "note": project_details.get("note", ""),
                    "ocr": project_details.get("ocr", {}),
                    "extractionModelId": selected_model_id,
                    "completion": project_details.get("completion", "manual"),
                    "duplicates": project_details.get("duplicates", "allow"),
                    "members": {"allow": "all"},
                    "schema": project_schema,
                    "retentionDays": project_details.get("retentionDays", 180)
                }
                response = requests.post(create_project_url, json=new_project_payload, headers=headers)
                if response.status_code == 201:
                    new_project = response.json()
                    new_project_id = new_project.get("id")
                    project_id_map[project_id] = new_project_id
                    project_name_map[project_id] = final_project_name
                    project_name_map[new_project_id] = final_project_name
                    st.success(f"Project '{final_project_name}' created successfully!")
                else:
                    st.error(f"Failed to create project '{final_project_name}'. Status code: {response.status_code}")
            else:
                st.error(f"Failed to retrieve details for project '{project_name}'.")
        st.session_state["project_map"] = project_id_map
        st.session_state["project_name_map"] = project_name_map

    saved_project_map = st.session_state.get("project_map", {})
    saved_project_names = st.session_state.get("project_name_map", {})
    if saved_project_map:
        st.subheader("Project ID Mapping")
        _display_project_mapping(saved_project_map, saved_project_names)
        st.info("Project copies are ready. You can now copy the routing rules using this mapping.")
        if st.button("Copy Routing Rules", key="copy_routing_rules_from_copy_projects_page"):
            copy_routing_rules_with_map(
                source_auth,
                target_auth,
                saved_project_map,
                saved_project_names,
            )

# --- Copy Routing Rules Section ---
def _format_project_label(project_id, project_names):
    project_name = project_names.get(project_id)
    if project_name:
        return f"{project_name} ({project_id})"
    return project_id or "Unknown project"


def _display_routing_copy_results(copied, skipped, failed, results):
    st.subheader("Summary")
    st.write(f"**Copied:** {len(copied)} | **Skipped:** {skipped} | **Failed:** {failed}")

    if copied:
        st.subheader("Routing Rule Mapping (Original ID -> New ID)")
        st.write(copied)

    if results:
        st.subheader("Routing Rule Copy Details")
        st.dataframe(
            results,
            use_container_width=True,
            hide_index=True,
            column_order=[
                "status",
                "rule_id",
                "new_rule_id",
                "source_route",
                "target_route",
                "reason",
            ],
        )


def _display_project_mapping(project_id_map, project_names=None):
    project_names = project_names or {}
    mapping_rows = []
    for source_id, target_id in project_id_map.items():
        mapping_rows.append({
            "source_project": _format_project_label(source_id, project_names),
            "target_project": _format_project_label(target_id, project_names),
        })

    if mapping_rows:
        st.dataframe(mapping_rows, use_container_width=True, hide_index=True)
    else:
        st.write(project_id_map)


def copy_routing_rules_with_map(source_auth, target_auth, project_id_map, project_names=None):
    """
    Copy routing rules whose source from/to project IDs are both present in project_id_map.
    project_id_map maps source project IDs to target project IDs.
    """
    st.subheader("Copying Routing Rules")
    st.info(
        "Scanning source routing rules, copying only the rules where both the source "
        "and destination projects are included in the project mapping below."
    )

    rule_ids = source_auth.get_all_routing_rule_ids(limit=50)
    if rule_ids is None:
        st.error("Failed to retrieve routing rule IDs.")
        return

    st.write(f"Found **{len(rule_ids)}** routing rules in the source company.")
    if not rule_ids:
        st.info("No routing rules were found in the source company.")
        _display_routing_copy_results({}, 0, 0, [])
        return

    copied = {}
    skipped = 0
    failed = 0
    project_names = project_names or {}
    results = []

    progress_bar = st.progress(0)
    progress_text = st.empty()

    for index, rid in enumerate(rule_ids, start=1):
        progress_text.write(f"Checking routing rule {index} of {len(rule_ids)}: `{rid}`")
        rule_details = source_auth.get_routing_by_id(rid)
        if rule_details is None:
            failed += 1
            results.append({
                "status": "Failed",
                "rule_id": rid,
                "new_rule_id": "",
                "source_route": "Unknown",
                "target_route": "",
                "reason": "Could not retrieve routing rule details from the source company.",
            })
            progress_bar.progress(index / len(rule_ids))
            continue

        original_from = rule_details.get("fromProjectId")
        original_to = rule_details.get("toProjectId")
        source_route = (
            f"{_format_project_label(original_from, project_names)} -> "
            f"{_format_project_label(original_to, project_names)}"
        )

        if original_from not in project_id_map or original_to not in project_id_map:
            skipped += 1
            missing_projects = []
            if original_from not in project_id_map:
                missing_projects.append("from project")
            if original_to not in project_id_map:
                missing_projects.append("to project")
            results.append({
                "status": "Skipped",
                "rule_id": rid,
                "new_rule_id": "",
                "source_route": source_route,
                "target_route": "",
                "reason": f"Skipped because the mapped selection does not include the {' and '.join(missing_projects)}.",
            })
            progress_bar.progress(index / len(rule_ids))
            continue

        new_from = project_id_map[original_from]
        new_to = project_id_map[original_to]
        target_route = (
            f"{_format_project_label(new_from, project_names)} -> "
            f"{_format_project_label(new_to, project_names)}"
        )
        new_rule_payload = dict(rule_details)
        new_rule_payload["fromProjectId"] = new_from
        new_rule_payload["toProjectId"] = new_to

        for field in ["id", "createdAt", "updatedAt"]:
            new_rule_payload.pop(field, None)

        new_rule = target_auth.create_routing_rule(new_rule_payload)
        if new_rule:
            new_rule_id = new_rule.get("id")
            copied[rid] = new_rule_id
            results.append({
                "status": "Copied",
                "rule_id": rid,
                "new_rule_id": new_rule_id,
                "source_route": source_route,
                "target_route": target_route,
                "reason": "Created in the target company.",
            })
        else:
            failed += 1
            results.append({
                "status": "Failed",
                "rule_id": rid,
                "new_rule_id": "",
                "source_route": source_route,
                "target_route": target_route,
                "reason": "Target API did not create the routing rule.",
            })

        progress_bar.progress(index / len(rule_ids))

    progress_text.write("Finished copying routing rules.")

    if copied:
        st.success(f"Copied {len(copied)} routing rules.")
    if skipped:
        st.warning(f"Skipped {skipped} routing rules because their projects were not fully mapped.")
    if failed:
        st.error(f"Failed to copy {failed} routing rules.")

    _display_routing_copy_results(copied, skipped, failed, results)


def copy_routing_rules_section():
    st.title("Copy Routing Rules")
    st.write("Copy routing rules using the project mapping from the project copy step, or map existing projects manually.")

    if "source_auth" not in st.session_state or "target_auth" not in st.session_state:
        st.error("Both source and target authentication are required.")
        return

    source_auth = st.session_state["source_auth"]
    target_auth = st.session_state["target_auth"]

    saved_project_map = st.session_state.get("project_map", {})
    saved_project_names = st.session_state.get("project_name_map", {})
    if saved_project_map:
        st.subheader("Saved Project Mapping")
        st.info("This mapping was created by the last Copy Projects run and can be reused directly.")
        _display_project_mapping(saved_project_map, saved_project_names)

        col_copy, col_clear = st.columns([1, 3])
        with col_copy:
            if st.button("Copy Routing Rules", key="copy_routing_rules_from_saved_map"):
                copy_routing_rules_with_map(
                    source_auth,
                    target_auth,
                    saved_project_map,
                    saved_project_names,
                )
                return
        with col_clear:
            if st.button("Clear Saved Mapping", key="clear_saved_project_map"):
                st.session_state.pop("project_map", None)
                st.session_state.pop("project_name_map", None)
                st.rerun()

        with st.expander("Map existing projects manually instead"):
            _manual_copy_routing_rules_section(source_auth, target_auth)
        return

    _manual_copy_routing_rules_section(source_auth, target_auth)


def _manual_copy_routing_rules_section(source_auth, target_auth):
    st.subheader("Manual Project Mapping")

    source_data = source_auth.get_projects()
    target_data = target_auth.get_projects()
    if not source_data:
        st.error("Failed to retrieve source projects.")
        return
    if not target_data:
        st.error("Failed to retrieve target projects.")
        return

    source_projects = source_data.get("data", [])
    target_projects = target_data.get("data", [])
    if not source_projects:
        st.info("No source projects found.")
        return
    if not target_projects:
        st.info("No target projects found.")
        return

    source_project_list = [(proj["id"], proj["name"]) for proj in source_projects]
    target_project_list = [(proj["id"], proj["name"]) for proj in target_projects]
    target_options = [None] + target_project_list
    target_by_name = {proj["name"]: (proj["id"], proj["name"]) for proj in target_projects}

    selected_sources = st.multiselect(
        "Source Projects",
        source_project_list,
        format_func=lambda x: x[1],
        key="routing_source_projects",
    )

    if not selected_sources:
        st.info("Select the source projects that participate in the routing rules you want to copy.")
        return

    st.subheader("Target Project Mapping")
    project_id_map = {}
    project_names = {}
    mapping_complete = True

    for source_id, source_name in selected_sources:
        default_target = target_by_name.get(source_name)
        default_index = target_options.index(default_target) if default_target in target_options else 0
        selected_target = st.selectbox(
            f"Target project for '{source_name}'",
            target_options,
            index=default_index,
            format_func=lambda x: "Select a target project" if x is None else x[1],
            key=f"routing_target_for_{source_id}",
        )
        if selected_target:
            project_id_map[source_id] = selected_target[0]
            project_names[source_id] = source_name
            project_names[selected_target[0]] = selected_target[1]
        else:
            mapping_complete = False

    st.subheader("Project ID Mapping")
    st.write(project_id_map)

    if st.button("Copy Routing Rules", key="copy_selected_routing_rules"):
        if not mapping_complete or not project_id_map:
            st.error("Please map every selected source project to a target project.")
            return
        copy_routing_rules_with_map(source_auth, target_auth, project_id_map, project_names)

# --- Clone from Template Company Section ---
ALLOWED_CLIENT_ID = "Lh8CbOZDvxLegwX21aLAjenUCbesYRia"

def clone_by_project_setup_section():
    st.title("Clone from Template Company Setup")

    # Gate access by source client_id.
    source_client_id = st.session_state.get("sourcecompany_user", "")
    if source_client_id != ALLOWED_CLIENT_ID:
        st.error("This section is only available when the Source Company client_id is the authorized template account.")
        return

    if "source_auth" not in st.session_state or "target_auth" not in st.session_state:
        st.error("Both source and target authentication must be completed.")
        return

    source_auth = st.session_state["source_auth"]
    target_auth = st.session_state["target_auth"]

    # Retrieve source projects.
    data = source_auth.get_projects()
    if not data:
        st.error("Failed to retrieve projects from the source company.")
        return
    projects = data.get("data", [])
    if not projects:
        st.error("No projects found in the source company.")
        return

    # Retrieve target projects for model ID selection.
    target_data = target_auth.get_projects()
    if not target_data:
        st.error("Failed to retrieve projects from the target company.")
        return
    target_projects = target_data.get("data", [])
    if not target_projects:
        st.error("No projects found in the target company.")
        return

    # Model ID selection (same pattern as Copy Projects).
    st.subheader("New Project Details")
    with st.expander("See explanation for Model ID"):
        st.write('''
            How to find the modelId?

            Select a project from the target company that has the correct model setup. If you don't have one, create a new project in the target company with the following parameters:
            - Choose any "Name" for your Project.
            - In "Model configuration", select "Hypatos AI Agent";
            - In Datapoints, select "Invoice EU/US" depending on the region of the project you are setting up;
            - Click "Next" -> don't change the datapoints structure -> click "Create";
            Then refresh the page and select that project to get the model ID.
        ''')

    target_project_list = [(proj["id"], proj["name"]) for proj in target_projects]
    selected_target_project = st.selectbox(
        "Select Target Project for Model ID",
        target_project_list,
        format_func=lambda x: x[1],
        key="setup_model_id_project",
    )
    selected_model_id = None
    if selected_target_project:
        for proj in target_projects:
            if proj["id"] == selected_target_project[0]:
                selected_model_id = proj.get("extractionModelId")
                st.write(f"Selected Model ID: {selected_model_id}")
                break

    # Setup selection.
    st.subheader("Select Project Setup")
    setup = st.radio(
        "Choose a setup",
        ["Setup A", "Setup B"],
        captions=[
            "No studio users - documents will not be validated/confirmed by a human in the loop in studio",
            "Studio users - documents will be validated and confirmed by a human in the loop in studio",
        ],
        key="clone_setup_type",
    )

    tag = "[A]" if setup == "Setup A" else "[B]"

    # Find projects matching the selected setup tag.
    selected_projects = [(proj["id"], proj["name"]) for proj in projects if tag in proj["name"]]

    st.subheader(f"Projects to Copy ({len(selected_projects)})")
    if selected_projects:
        for _, name in selected_projects:
            st.write(f"- {name}")
    else:
        st.info(f"No projects found matching tag `{tag}`.")

    if st.button("Create Project Copies", key="setup_create_copies"):
        if not selected_target_project or not selected_model_id:
            st.error("Please select a target project for the model ID.")
            return
        if not selected_projects:
            st.error("Please select at least one project to copy.")
            return

        headers = target_auth.get_headers()
        create_project_url = f"{target_auth.base_url}/projects"
        project_id_map = {}

        for project_id, project_name in selected_projects:
            project_details = source_auth.get_project_by_id(project_id)
            project_schema = source_auth.get_project_schema(project_id)
            if project_details and project_schema:
                new_project_payload = {
                    "name": project_name,
                    "note": project_details.get("note", ""),
                    "ocr": project_details.get("ocr", {}),
                    "extractionModelId": selected_model_id,
                    "completion": project_details.get("completion", "manual"),
                    "duplicates": project_details.get("duplicates", "allow"),
                    "members": {"allow": "all"},
                    "schema": project_schema,
                    "retentionDays": project_details.get("retentionDays", 180),
                }
                response = requests.post(create_project_url, json=new_project_payload, headers=headers)
                if response.status_code == 201:
                    new_project = response.json()
                    new_project_id = new_project.get("id")
                    project_id_map[project_id] = new_project_id
                    st.success(f"Project '{project_name}' created successfully!")
                else:
                    st.error(f"Failed to create project '{project_name}'. Status code: {response.status_code}")
            else:
                st.error(f"Failed to retrieve details for project '{project_name}'.")

        project_name_map = {}
        for orig_id, new_id in project_id_map.items():
            for proj_id, proj_name in selected_projects:
                if proj_id == orig_id:
                    project_name_map[orig_id] = proj_name
                    project_name_map[new_id] = proj_name
                    break

        st.session_state["project_map"] = project_id_map
        st.session_state["project_name_map"] = project_name_map

        # Automatically copy routing rules for the mapped projects
        # Ensure auth objects are present
        if "source_auth" not in st.session_state or "target_auth" not in st.session_state:
            st.error("Both source and target authentication are required to copy routing rules.")
        else:
            source_auth_local = st.session_state["source_auth"]
            target_auth_local = st.session_state["target_auth"]

            copy_routing_rules_with_map(
                source_auth_local,
                target_auth_local,
                project_id_map,
                project_name_map,
            )


# ---------- Get Model ID Section ----------

def get_model_id_section():
    st.title("Get Extraction Model ID of Target Company Project")
    if "target_auth" not in st.session_state:
        st.error("Target authentication not found. Please authenticate with target company credentials.")
        return

    target_auth = st.session_state["target_auth"]
    # Retrieve projects with limit=200 from target.
    projects_url = f"{target_auth.base_url}/projects"
    headers = target_auth.get_headers()
    query = {"limit": "200"}
    response = requests.get(projects_url, headers=headers, params=query)
    if response.status_code != 200:
        st.error(f"Failed to retrieve projects from target company. Status code: {response.status_code}")
        return
    data = response.json()
    projects = data.get("data", [])
    if not projects:
        st.info("No projects found for target company.")
        return

    project_list = [(proj["id"], proj["name"]) for proj in projects]
    selected_project = st.selectbox("Select Project", project_list, format_func=lambda x: x[1])
    if st.button("Get Model ID"):
        # Find the project details from the list by matching the project ID.
        for proj in projects:
            if proj["id"] == selected_project[0]:
                st.write("Extraction Model ID:", proj.get("extractionModelId"))
                break

# --- Credentials helper for Clone from Template Company Setup (source from secrets) ---

def _input_target_credentials_only():
    """Show only target credentials; source credentials are loaded from st.secrets."""
    st.header("Company Credentials")
    st.selectbox(
        "Source API Region",
        (BASE_URL_EU, BASE_URL_US),
        key="source_base_url",
        format_func=lambda url: "EU - api.cloud.hypatos.ai" if url == BASE_URL_EU else "US - api.cloud.hypatos.com",
    )
    st.info("Source Company credentials are pre-configured (loaded from secrets).")
    st.subheader("Target Company")
    st.selectbox(
        "Target API Region",
        (BASE_URL_EU, BASE_URL_US),
        key="target_base_url",
        format_func=lambda url: "EU - api.cloud.hypatos.ai" if url == BASE_URL_EU else "US - api.cloud.hypatos.com",
    )
    st.text_input("Target Company client_id", key="targetcompany_user")
    st.text_input("Target Company client_secret", type="password", key="targetcompany_apipw")


# --- Main App Navigation ---

def main():
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Select Action",
                            ["Clone from Template Company Setup", "Copy Projects", "Copy Routing Rules", "Get Model ID", "Clear Session State"])

    # Credentials input: source is pre-loaded from secrets for "Clone from Template Company Setup".
    if page == "Clone from Template Company Setup":
        st.session_state["sourcecompany_user"] = st.secrets["CLIENT_ID"]
        st.session_state["sourcecompany_apipw"] = st.secrets["CLIENT_SECRET"]
        _input_target_credentials_only()
    else:
        input_credentials()
    if st.button("Authenticate Credentials"):
        authenticate_credentials()

    if page == "Copy Projects":
        copy_projects_section()
    elif page == "Clone from Template Company Setup":
        clone_by_project_setup_section()
    elif page == "Copy Routing Rules":
        copy_routing_rules_section()
    elif page == "Get Model ID":
        get_model_id_section()
    elif page == "Clear Session State":
        clear_session_state_generic()

if __name__ == "__main__":
    main()
