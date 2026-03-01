import streamlit as st
from helpers import check_admin_access

st.set_page_config(page_title="Copy Agent Workflow", layout="wide")
st.title("Copy Agent Workflow")

if not check_admin_access():
    st.stop()

st.info("Admin access granted. Implementation coming soon.")
