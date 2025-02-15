import streamlit as st
from config import BASE_URL_EU, BASE_URL_US
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
