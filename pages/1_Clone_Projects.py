import streamlit as st
import requests
from auth import HypatosAPI  
from helpers import input_credentials,clear_session_state_generic


st.set_page_config(page_title="Clone Projects", page_icon=":cyclone:")

# --- Authentication Section (Always at Top) ---
def authenticate_credentials():
    """Authenticate both source and target credentials and store them separately."""
    source_user = st.session_state.get("sourcecompany_user", "")
    source_pw = st.session_state.get("sourcecompany_apipw", "")
    target_user = st.session_state.get("targetcompany_user", "")
    target_pw = st.session_state.get("targetcompany_apipw", "")
    base_url = st.session_state.get("base_url", "")

    errors = False
    if not source_user or not source_pw:
        st.error("Please provide Source Company credentials.")
        errors = True
    if not target_user or not target_pw:
        st.error("Please provide Target Company credentials.")
        errors = True
    if errors:
        return

    source_auth = HypatosAPI(source_user, source_pw, base_url)
    target_auth = HypatosAPI(target_user, target_pw, base_url)
    
    if source_auth.authenticate():
        st.success("Source Authentication succeeded!")
        st.session_state["source_auth"] = source_auth
    else:
        st.error("Source Authentication failed.")
    
    if target_auth.authenticate():
        st.success("Target Authentication succeeded!")
        st.session_state["target_auth"] = target_auth
    else:
        st.error("Target Authentication failed.")

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
            - In Datapoints, select "Invoice EU/US" depending on the region of the project you are setting up;
            - Click "Next" -> don't change the datapoints structure -> click "Create";
            Then refresh the page and select that project to get the model ID.
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
                    st.success(f"Project '{final_project_name}' created successfully!")
                else:
                    st.error(f"Failed to create project '{final_project_name}'. Status code: {response.status_code}")
            else:
                st.error(f"Failed to retrieve details for project '{project_name}'.")
        st.session_state["project_map"] = project_id_map
        st.subheader("Project ID Mapping")
        st.write(project_id_map)
        st.write('You can now copy the routing rules: Click Copy Routing Rules on the left')

# --- Copy Routing Rules Section ---
def copy_routing_rules_section():
    st.title("Copy Routing Rules")
    if "project_map" not in st.session_state or not st.session_state["project_map"]:
        st.error("No project mapping found. Please complete the project copy phase first.")
        return

    st.subheader("Project Mapping")
    st.write("Mapping:", st.session_state["project_map"])
    
    # Use source_auth for reading routing rules and target_auth for posting.
    if "source_auth" not in st.session_state or "target_auth" not in st.session_state:
        st.error("Both source and target authentication are required.")
        return

    source_auth = st.session_state["source_auth"]
    target_auth = st.session_state["target_auth"]
    
    if st.button("Copy Routing Rules"):
        # Retrieve all routing rule IDs using source_auth.
        rule_ids = source_auth.get_all_routing_rule_ids(limit=100)
        
        if rule_ids is None:
            st.error("Failed to retrieve routing rule IDs.")
            return

        st.write(rule_ids)
        
        new_rules_mapping = {}
        for rid in rule_ids:
            rule_details = source_auth.get_routing_by_id(rid)
            if rule_details is None:
                st.warning(f"Could not retrieve details for routing rule {rid}")
                continue
            original_from = rule_details.get("fromProjectId")
            original_to = rule_details.get("toProjectId")
            # Only process the rule if both IDs are present in the mapping.
            if original_from in st.session_state["project_map"] and original_to in st.session_state["project_map"]:
                rule_details["fromProjectId"] = st.session_state["project_map"][original_from]
                rule_details["toProjectId"] = st.session_state["project_map"][original_to]
            else:
                st.info(f"Skipping rule {rid}: project mapping incomplete (from: {original_from}, to: {original_to})")
                continue

            # Remove fields that should not be part of the creation payload.
            for field in ["id", "createdAt", "updatedAt"]:
                rule_details.pop(field, None)
            # Create new routing rule using target_auth.
            new_rule = target_auth.create_routing_rule(rule_details)
            if new_rule:
                new_rules_mapping[rid] = new_rule.get("id")
            else:
                st.error(f"Failed to create new routing rule for original rule {rid}")
        st.subheader("Routing Rule Mapping (Original ID → New ID)")
        st.write(new_rules_mapping)

# --- Clone by Project Setup Section ---
ALLOWED_CLIENT_ID = "Lh8CbOZDvxLegwX21aLAjenUCbesYRia"

def clone_by_project_setup_section():
    st.title("Clone by Project Setup")

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

    # Reset multiselect when setup type changes so the default re-applies.
    if st.session_state.get("_prev_setup_type") != setup:
        st.session_state["_prev_setup_type"] = setup
        st.session_state.pop("setup_selected_projects", None)

    # Auto-select projects matching the tag.
    project_list = [(proj["id"], proj["name"]) for proj in projects]
    auto_selected = [p for p in project_list if tag in p[1]]

    st.subheader("Projects to Copy")
    selected_projects = st.multiselect(
        "Projects",
        project_list,
        default=auto_selected,
        format_func=lambda x: x[1],
        key="setup_selected_projects",
    )
    st.write(f"**{len(selected_projects)}** project(s) selected.")

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

        st.session_state["project_map"] = project_id_map
        st.subheader("Project ID Mapping")
        st.write(project_id_map)
        st.write("You can now copy the routing rules: Click Copy Routing Rules on the left")


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

# --- Main App Navigation ---

def main():
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Select Action",
                            ["Copy Projects", "Clone by Project Setup", "Copy Routing Rules", "Get Model ID", "Clear Session State"])

    # Always show the credentials input at the top.
    input_credentials()
    if st.button("Authenticate Credentials"):
        authenticate_credentials()

    if page == "Copy Projects":
        copy_projects_section()
    elif page == "Clone by Project Setup":
        clone_by_project_setup_section()
    elif page == "Copy Routing Rules":
        copy_routing_rules_section()
    elif page == "Get Model ID":
        get_model_id_section()
    elif page == "Clear Session State":
        clear_session_state_generic()

if __name__ == "__main__":
    main()
