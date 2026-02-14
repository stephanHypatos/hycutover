import streamlit as st
from auth import HypatosAPI
from helpers import input_credentials, clear_session_state_generic


st.set_page_config(page_title="Config Clone & Update", page_icon=":gear:")


# --- Authentication Section ---
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


# --- Update Project Configuration ---
def update_config_section():
    st.title("Update Project Configuration")
    st.write("Update configuration fields on an existing project.")

    if "target_auth" not in st.session_state:
        st.error("Please authenticate first.")
        return

    target_auth = st.session_state["target_auth"]

    # Retrieve projects from target company.
    data = target_auth.get_projects()
    if not data:
        st.error("Failed to retrieve projects.")
        return
    projects = data.get("data", [])
    if not projects:
        st.info("No projects found.")
        return

    project_list = [(proj["id"], proj["name"]) for proj in projects]
    selected_project = st.selectbox(
        "Select Project to Update",
        project_list,
        format_func=lambda x: x[1],
        key="update_config_project",
    )

    if selected_project:
        project_details = target_auth.get_project_by_id(selected_project[0])
        if not project_details:
            st.error("Failed to retrieve project details.")
            return

        st.subheader("Current Configuration")
        current_completion = project_details.get("completion", "manual")
        current_duplicates = project_details.get("duplicates", "fail")
        current_retention = project_details.get("retentionDays", 180)
        current_is_live = project_details.get("isLive", False)

        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Completion:** {current_completion}")
            st.write(f"**Duplicates:** {current_duplicates}")
        with col2:
            st.write(f"**Retention Days:** {current_retention}")
            st.write(f"**Is Live:** {current_is_live}")

        st.subheader("New Configuration")
        new_completion = st.selectbox(
            "Completion",
            ["manual", "automatic"],
            index=0 if current_completion == "manual" else 1,
            key="update_completion",
        )
        new_duplicates = st.selectbox(
            "Duplicates",
            ["allow", "fail"],
            index=0 if current_duplicates == "allow" else 1,
            key="update_duplicates",
        )
        new_retention = st.number_input(
            "Retention Days",
            min_value=1,
            max_value=3650,
            value=current_retention,
            key="update_retention",
        )
        new_is_live = st.checkbox(
            "Is Live",
            value=current_is_live,
            key="update_is_live",
        )

        if st.button("Update Configuration"):
            payload = {
                "completion": new_completion,
                "duplicates": new_duplicates,
                "retentionDays": new_retention,
                "isLive": new_is_live,
            }
            result = target_auth.update_project(selected_project[0], payload)
            if result:
                st.success(f"Project '{selected_project[1]}' updated successfully!")
                st.json(result)
            else:
                st.error(f"Failed to update project '{selected_project[1]}'.")


# --- Clone Configuration ---
def clone_config_section():
    st.title("Clone Project Configuration")
    st.write(
        "Clone configuration (completion, duplicates, retentionDays, isLive) "
        "from a source project to a target project."
    )

    if "source_auth" not in st.session_state or "target_auth" not in st.session_state:
        st.error("Both source and target authentication must be completed.")
        return

    source_auth = st.session_state["source_auth"]
    target_auth = st.session_state["target_auth"]

    # Source projects
    source_data = source_auth.get_projects()
    if not source_data:
        st.error("Failed to retrieve source projects.")
        return
    source_projects = source_data.get("data", [])
    if not source_projects:
        st.info("No source projects found.")
        return

    # Target projects
    target_data = target_auth.get_projects()
    if not target_data:
        st.error("Failed to retrieve target projects.")
        return
    target_projects = target_data.get("data", [])
    if not target_projects:
        st.info("No target projects found.")
        return

    col_src, col_tgt = st.columns(2)
    with col_src:
        source_list = [(p["id"], p["name"]) for p in source_projects]
        selected_source = st.selectbox(
            "Source Project",
            source_list,
            format_func=lambda x: x[1],
            key="clone_config_source",
        )
    with col_tgt:
        target_list = [(p["id"], p["name"]) for p in target_projects]
        selected_target = st.selectbox(
            "Target Project",
            target_list,
            format_func=lambda x: x[1],
            key="clone_config_target",
        )

    if selected_source:
        source_details = source_auth.get_project_by_id(selected_source[0])
        if source_details:
            st.subheader("Source Project Configuration")
            st.json({
                "completion": source_details.get("completion"),
                "duplicates": source_details.get("duplicates"),
                "retentionDays": source_details.get("retentionDays"),
                "isLive": source_details.get("isLive"),
            })

    if st.button("Clone Configuration"):
        if not selected_source or not selected_target:
            st.error("Please select both source and target projects.")
            return

        source_details = source_auth.get_project_by_id(selected_source[0])
        if not source_details:
            st.error("Failed to retrieve source project details.")
            return

        payload = {
            "completion": source_details.get("completion", "manual"),
            "duplicates": source_details.get("duplicates", "fail"),
            "retentionDays": source_details.get("retentionDays", 180),
            "isLive": source_details.get("isLive", False),
        }

        result = target_auth.update_project(selected_target[0], payload)
        if result:
            st.success(
                f"Configuration cloned from '{selected_source[1]}' to '{selected_target[1]}' successfully!"
            )
            st.json(result)
        else:
            st.error(
                f"Failed to clone configuration to '{selected_target[1]}'."
            )


# --- Clone Schema ---
def clone_schema_section():
    st.title("Clone Project Schema")
    st.write(
        "Clone the schema (datapoints structure) from a source project to a target project."
    )

    if "source_auth" not in st.session_state or "target_auth" not in st.session_state:
        st.error("Both source and target authentication must be completed.")
        return

    source_auth = st.session_state["source_auth"]
    target_auth = st.session_state["target_auth"]

    # Source projects
    source_data = source_auth.get_projects()
    if not source_data:
        st.error("Failed to retrieve source projects.")
        return
    source_projects = source_data.get("data", [])
    if not source_projects:
        st.info("No source projects found.")
        return

    # Target projects
    target_data = target_auth.get_projects()
    if not target_data:
        st.error("Failed to retrieve target projects.")
        return
    target_projects = target_data.get("data", [])
    if not target_projects:
        st.info("No target projects found.")
        return

    col_src, col_tgt = st.columns(2)
    with col_src:
        source_list = [(p["id"], p["name"]) for p in source_projects]
        selected_source = st.selectbox(
            "Source Project",
            source_list,
            format_func=lambda x: x[1],
            key="clone_schema_source",
        )
    with col_tgt:
        target_list = [(p["id"], p["name"]) for p in target_projects]
        selected_target = st.selectbox(
            "Target Project",
            target_list,
            format_func=lambda x: x[1],
            key="clone_schema_target",
        )

    if selected_source:
        source_schema = source_auth.get_project_schema(selected_source[0])
        if source_schema:
            datapoints = source_schema.get("dataPoints", [])
            st.subheader("Source Schema Preview")
            st.write(f"Number of top-level datapoints: {len(datapoints)}")
            with st.expander("View Full Schema"):
                st.json(source_schema)

    if st.button("Clone Schema"):
        if not selected_source or not selected_target:
            st.error("Please select both source and target projects.")
            return

        source_schema = source_auth.get_project_schema(selected_source[0])
        if not source_schema:
            st.error("Failed to retrieve source project schema.")
            return

        payload = {"schema": source_schema}
        result = target_auth.update_project(selected_target[0], payload)
        if result:
            st.success(
                f"Schema cloned from '{selected_source[1]}' to '{selected_target[1]}' successfully!"
            )
            st.json(result)
        else:
            st.error(
                f"Failed to clone schema to '{selected_target[1]}'."
            )


# --- Main Navigation ---
def main():
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select Action",
        [
            "Update Configuration",
            "Clone Configuration",
            "Clone Schema",
            "Clear Session State",
        ],
    )

    # Always show the credentials input at the top.
    input_credentials()
    if st.button("Authenticate Credentials"):
        authenticate_credentials()

    if page == "Update Configuration":
        update_config_section()
    elif page == "Clone Configuration":
        clone_config_section()
    elif page == "Clone Schema":
        clone_schema_section()
    elif page == "Clear Session State":
        clear_session_state_generic()


if __name__ == "__main__":
    main()
