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
st.subheader("Prerequisite")

st.markdown('''
    1. API v2 credentials of source and target company 
    2. API credentials must include the following scopes: 
        - projects.read
        - projects.write
        - routings.read
        - routings.write
        - **[Read more here](https://docs-internal.hypatos.ai/implementation-playbook/introduction-to-implementation-playbook/implementation-playbook/create-or-update-keycloak-credentials)**
''')