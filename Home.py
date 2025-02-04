import streamlit as st

st.set_page_config(page_title="HyCutOver", page_icon=":haircut:")

st.title("✂️ HYCUTOVER")
st.sidebar.success("Select a page.")
st.subheader("Introduction")
st.write(
    """
    This application allows you to:
    - Compare two project schemas.
    - Clone projects and their attached routing rules.
    """
)

with st.expander("Documentation"):
        st.markdown(
            '''
        ### Overview
        This is a Streamlit-based web application that provides functionalities for comparing schemas at a detailed level and copying projects within one or between two companies using API authentication. The app consists of two main functionalities:

        1. **Schema Comparison**
        - Authenticates source and target company credentials.
        - Fetches and compares schemas between selected projects.
        - Displays differences in data points and meta-level attributes.

        2. **Project Copying**
        - Copies projects from a source company to a target company.
        - Allows specifying a new extraction model ID.
        - Supports cloning routing rules of projects.

        ### Features
        - Secure API authentication using `HypatosAPI`.
        - Schema comparison at data point and meta levels using `DeepDiff`.
        - Copy projects with custom parameters.
        - Fetch and copy routing rules.
        - Retrieve extraction model ID from target projects.
       
        ### Prerequisites
        1. API v2 credentials of source and target company 
        2. API credentials must include the following scopes: 
        
        - projects.read
        - projects.write
        - routings.read
        - routings.write
        - **[Read more here](https://docs-internal.hypatos.ai/implementation-playbook/introduction-to-implementation-playbook/implementation-playbook/create-or-update-keycloak-credentials)**

        ### Usage
        #### Authentication
        - Enter the source and target company credentials.
        - Click "Authenticate Credentials" to verify.

        #### Schema Comparison
        1. Navigate to "Compare Datapoints" or "Compare Metadata".
        2. Select the source project.
        3. Select one or multiple target projects.
        4. Click "Compare" to see the differences.

        #### Project Copying
        1. Navigate to "Clone Projects".
        2. Select "Copy Projects".
        3. Enter the credentials.
        4. Select projects to copy.
        5. Enter a new extraction model ID.
        6. Click "Create Project Copies".
        7. Once ready you can now copy the routing rules.


        #### Copy Routing Rules
        1. Navigate to "Copy Routing Rules".
        2. Click "Copy Routing Rules" to transfer routing rules between projects.

        #### Get Model ID
        1. Navigate to "Get Model ID".
        2. Select a project to retrieve its extraction model ID.

        ### Technologies Used
        - **Python**
        - **Streamlit**
        - **Pandas**
        - **DeepDiff**
        - **Requests**

        ### Contact
        For any issues or feature requests, open an issue on the GitHub repository.

        '''

        )