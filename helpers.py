import streamlit as st
from config import BASE_URL_EU, BASE_URL_US

# Required scopes for API operations
REQUIRED_SCOPES = ["projects.read", "projects.write", "routings.read", "routings.write"]

# --- Helper Functions ---
def input_credentials():
    """Display two columns for source and target credentials."""
    st.header("Company Credentials")
    env_url = st.selectbox(
    "Select an Env: EU / US",
    (BASE_URL_EU, BASE_URL_US),
    key="base_url"
    )
    col_source, col_target = st.columns(2)
    with col_source:
        st.subheader("Source Company")
        source_user = st.text_input("Source Company client_id", key="sourcecompany_user")
        source_pw = st.text_input("Source Company client_secret", type="password", key="sourcecompany_apipw")
    with col_target:
        st.subheader("Target Company")
        target_user = st.text_input("Target Company client_id", key="targetcompany_user")
        target_pw = st.text_input("Target Company client_secret", type="password", key="targetcompany_apipw")
    st.write("If source and target are the same, please enter identical credentials.")

def clear_session_state_generic():
    """
    Displays a multiselect widget with all session state keys and clears
    the selected keys when the user clicks the clear button.
    """
    st.subheader("Clear Session State Keys")
    # Get a list of all keys in session state
    keys = list(st.session_state.keys())
    if not keys:
        st.info("No session state keys to clear.")
        return
    # Let the user select keys to clear
    keys_to_clear = st.multiselect("Select keys to clear", keys)
    if st.button("Clear Selected Keys"):
        for key in keys_to_clear:
            del st.session_state[key]
        st.success("Selected session state keys have been cleared.")

def validate_scopes(auth, company_name: str):
    """
    Validates if the authenticated client has all required scopes.
    Displays appropriate error message if scopes are missing.
    
    Args:
        auth: An instance of HypatosAPI with scope validation methods.
        company_name: Name of the company (for display purposes).
    
    Returns:
        bool: True if all required scopes are present, False otherwise.
    """
    if not auth.has_required_scopes(REQUIRED_SCOPES):
        missing_scopes = auth.get_missing_scopes(REQUIRED_SCOPES)
        st.error(
            f"❌ **{company_name}** is missing required API scopes.\n\n"
            f"**Missing Scopes:**\n"
            + "\n".join([f"- {scope}" for scope in missing_scopes]) +
            f"\n\nPlease contact your administrator to grant these scopes to your API credentials."
        )
        return False
    return True

def select_project_and_get_schema(auth):
    """
    Displays a selectbox listing all projects retrieved via the provided auth instance.
    When the user selects a project, it retrieves and returns that project's schema.
    Args:
        auth: An instance of HypatosAPI (or similar) with methods get_projects() and get_project_schema(project_id).
    Returns:
        dict: The schema of the selected project, or None if no project is selected or retrieval fails.
    """
    # Retrieve projects using the auth object.
    projects_data = auth.get_projects()
    projects = projects_data.get("data", [])
    if not projects:
        st.error("No projects found.")
        return None
    # Build a list of tuples: (project_id, project_name)
    project_list = [(proj["id"], proj["name"]) for proj in projects]
    
    # Display a selectbox for the user to choose a project.
    selected_project = st.selectbox("Select a Project", project_list, format_func=lambda x: x[1])
    
    # Retrieve the schema for the selected project.
    schema = auth.get_project_schema(selected_project[0])
    if schema:
        st.success(f"Schema for project '{selected_project[1]}' retrieved successfully.")
    else:
        st.error("Failed to retrieve the project schema.")
    return schema

def get_datapoints_dict(auth, project_id):
    """
    Retrieves the schema for a project and extracts datapoints into a dictionary.
    
    Args:
        auth: An instance of HypatosAPI with method get_project_schema(project_id).
        project_id: The ID of the project to retrieve datapoints from.
    
    Returns:
        dict: A dictionary of datapoints from the schema, or empty dict if retrieval fails.
    """
    schema = auth.get_project_schema(project_id)
    if not schema:
        return {}
    
    # Extract datapoints from schema
    # Adjust this based on your actual schema structure
    datapoints = schema.get("datapoints", {})
    return datapoints

def get_metadata(auth, project_id):
    """
    Retrieves the schema for a project and extracts metadata.
    
    Args:
        auth: An instance of HypatosAPI with method get_project_schema(project_id).
        project_id: The ID of the project to retrieve metadata from.
    
    Returns:
        dict: A dictionary of metadata from the schema, or empty dict if retrieval fails.
    """
    schema = auth.get_project_schema(project_id)
    if not schema:
        return {}
    
    # Extract metadata from schema (everything except datapoints)
    # Create a copy without datapoints
    metadata = {k: v for k, v in schema.items() if k != "datapoints"}
    return metadata
