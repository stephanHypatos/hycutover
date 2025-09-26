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

    project_list = [(proj["id"], proj["name"]) for proj in projects]
    st.subheader("Select Projects to Copy")
    selected_projects = st.multiselect("Projects", project_list, format_func=lambda x: x[1])
    st.subheader("New Project Details")
    new_model_id = st.text_input("New Extraction Model ID", key="new_model_id")
    with st.expander("See explanation"):
        st.write('''
            How to find the modelId?

            1. You already have a project with the correct model setup, created in the Target Company? 
               Go to Step 3 else proceed with Step 2.
            2. Create a new project in the target company with the following parameters:
                - Choose any projectname
                - Add a new  Model with the following params: 
                    - Modeldisplayname: Prompting Service (for standard prompting service projects)
                    - routing-header-name: invoice-extracter-prompting-service (for standard prompting service projects)
                - Select a schema
                - Click create
            3. Navigate to GetModelID in the left Menu on this page.
            4. Select the Project.
            5. Copy the modelId and paste it into 'New Extraction Model ID'.
        ''')
    
    new_project_name_prefix = st.text_input("Prefix for New Project Names (optional)", key="new_project_name_prefix")

    if st.button("Create Project Copies"):
        if not new_model_id:
            st.error("Please provide a new Extraction Model ID.")
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
                if new_project_name_prefix:
                    final_project_name = f"{new_project_name_prefix}{project_name}"
                else:
                    final_project_name = project_name

                new_project_payload = {
                    "name": final_project_name,
                    "note": project_details.get("note", ""),
                    "ocr": project_details.get("ocr", {}),
                    "extractionModelId": new_model_id,
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
                            ["Copy Projects", "Copy Routing Rules", "Get Model ID", "Clear Session State"])
    
    # Always show the credentials input at the top.
    input_credentials()
    if st.button("Authenticate Credentials"):
        authenticate_credentials()

    if page == "Copy Projects":
        copy_projects_section()
    elif page == "Copy Routing Rules":
        copy_routing_rules_section()
    elif page == "Get Model ID":
        get_model_id_section()        
    elif page == "Clear Session State":
        clear_session_state_generic()

if __name__ == "__main__":
    main()
