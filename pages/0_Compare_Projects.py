import streamlit as st
import pandas as pd
from deepdiff import DeepDiff
from auth import HypatosAPI  # Your authentication class
from config import BASE_URL
from helpers import input_credentials

st.set_page_config(page_title="Very Low Level Schema Compare", page_icon=":mag:")

# --- Authentication Section (Always at Top) ---
def authenticate_credentials():
    """Authenticate both source and target credentials and store them separately."""
    source_user = st.session_state.get("sourcecompany_user", "")
    source_pw = st.session_state.get("sourcecompany_apipw", "")
    target_user = st.session_state.get("targetcompany_user", "")
    target_pw = st.session_state.get("targetcompany_apipw", "")

    errors = False
    if not source_user or not source_pw:
        st.error("Please provide Source Company credentials.")
        errors = True
    if not target_user or not target_pw:
        st.error("Please provide Target Company credentials.")
        errors = True
    if errors:
        return

    source_auth = HypatosAPI(source_user, source_pw, BASE_URL)
    target_auth = HypatosAPI(target_user, target_pw, BASE_URL)
    
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


# --- Flatten Schema Function ---

def flatten_schema(datapoints, parent=""):
    """
    Recursively flattens a list of datapoint dictionaries.
    Each datapoint is keyed by its internalName. If a datapoint contains a nested
    list of datapoints (under the key "dataPoints"), these are flattened with a composite key.
    For example, a datapoint with internalName "items" having nested datapoints with internalName "C"
    will be represented with the composite key "items.C".
    
    Returns a dict mapping composite keys to datapoint dictionaries.
    """
    flat = {}
    for dp in datapoints:
        key = dp.get("internalName", "unknown")
        composite_key = f"{parent}.{key}" if parent else key
        flat[composite_key] = dp
        # Look for nested datapoints under "dataPoints" key.
        if "dataPoints" in dp and isinstance(dp["dataPoints"], list) and dp["dataPoints"]:
            nested = flatten_schema(dp["dataPoints"], parent=composite_key)
            flat.update(nested)
    return flat

# --- Compare Schema Function ---

def compare_schemas_very_low(source_schema, target_schema, target_project_name):
    """
    Compares two schemas at a very detailed level.
    Both schemas are expected to have a "dataPoints" list.
    This function flattens the datapoints recursively (using the nested "dataPoints" key)
    so that nested datapoints are given composite keys (e.g. "items.C").
    
    It then compares a set of attributes for each datapoint:
       internalName, displayName, type, rules, normalization, derivation, source.
    
    For each composite key in the union of source and target, differences are captured.
    Returns a list of difference records with columns:
       Target Project, Data Point, Attribute, Difference.
    """
    differences = []
    source_flat = flatten_schema(source_schema.get("dataPoints", []))
    target_flat = flatten_schema(target_schema.get("dataPoints", []))
    
    all_keys = set(source_flat.keys()).union(set(target_flat.keys()))
    attributes = ["internalName", "displayName", "type", "rules", "normalization", "derivation", "source"]
    
    for key in all_keys:
        if key not in target_flat:
            differences.append({
                "Target Project": target_project_name,
                "Data Point": key,
                "Attribute": "Entire datapoint",
                "Difference": "Missing in target"
            })
        elif key not in source_flat:
            differences.append({
                "Target Project": target_project_name,
                "Data Point": key,
                "Attribute": "Entire datapoint",
                "Difference": "Extra in target"
            })
        else:
            src_dp = source_flat[key]
            tgt_dp = target_flat[key]
            for attr in attributes:
                src_val = src_dp.get(attr)
                tgt_val = tgt_dp.get(attr)
                diff = DeepDiff(src_val, tgt_val, ignore_order=True, verbose_level=2)
                if diff:
                    differences.append({
                        "Target Project": target_project_name,
                        "Data Point": key,
                        "Attribute": attr,
                        "Difference": str(diff)
                    })
    return differences

def compare_datapoints_option():
    st.title("Compare Project Schemas")
    # Ensure that both source and target auth objects exist.
    if "source_auth" not in st.session_state or "target_auth" not in st.session_state:
        st.error("Please authenticate both Source and Target credentials first.")
        return
    
    source_auth = st.session_state["source_auth"]
    target_auth = st.session_state["target_auth"]
    
    # Retrieve project lists from source and target.
    source_data = source_auth.get_projects()
    target_data = target_auth.get_projects()
    source_projects = source_data.get("data", [])
    target_projects = target_data.get("data", [])
    
    if not source_projects:
        st.error("No source projects found.")
        return
    if not target_projects:
        st.error("No target projects found.")
        return
    
    # Build selection lists (tuples of (id, name))
    source_project_list = [(proj["id"], proj["name"]) for proj in source_projects]
    target_project_list = [(proj["id"], proj["name"]) for proj in target_projects]
    
    # Allow one source project.
    source_project = st.selectbox("Source Project", source_project_list, format_func=lambda x: x[1])
    # Allow multiple target projects (max 10).
    target_projects_selected = st.multiselect("Target Project(s) (max 10)", target_project_list, format_func=lambda x: x[1])
    if len(target_projects_selected) > 10:
        st.error("You can select a maximum of 10 target projects.")
        return
    
    if st.button("Compare"):
        # Retrieve source schema using source_auth.
        source_schema = source_auth.get_project_schema(source_project[0])
        if not source_schema:
            st.error("Failed to retrieve schema for the source project.")
            return
        
        all_differences = []
        for target_proj in target_projects_selected:
            target_proj_id, target_proj_name = target_proj
            target_schema = target_auth.get_project_schema(target_proj_id)
            if not target_schema:
                st.warning(f"Failed to retrieve schema for target project {target_proj_name}.")
                continue
            diffs = compare_schemas_very_low(source_schema, target_schema, target_proj_name)
            all_differences.extend(diffs)
        
        if all_differences:
            df = pd.DataFrame(all_differences, columns=["Target Project", "Data Point", "Attribute", "Difference"])
            st.subheader("Schema Differences")
            st.dataframe(df)
        else:
            st.success("No differences found at the datapoint level.")


# --- MetaLevel Compare Function ---

def compare_meta_level_section():
    st.title("Compare Project Metadata")
    # Ensure both auth objects are available.
    if "source_auth" not in st.session_state or "target_auth" not in st.session_state:
        st.error("Please authenticate both Source and Target credentials first.")
        return

    source_auth = st.session_state["source_auth"]
    target_auth = st.session_state["target_auth"]

    # Retrieve project lists from each company.
    source_data = source_auth.get_projects()
    target_data = target_auth.get_projects()
    source_projects = source_data.get("data", [])
    target_projects = target_data.get("data", [])

    if not source_projects:
        st.error("No source projects found.")
        return
    if not target_projects:
        st.error("No target projects found.")
        return

    source_project_list = [(proj["id"], proj["name"]) for proj in source_projects]
    target_project_list = [(proj["id"], proj["name"]) for proj in target_projects]

    # Allow one source project.
    source_project = st.selectbox("Source Project", source_project_list, format_func=lambda x: x[1])
    # Allow multiple target projects (max 10).
    target_projects_selected = st.multiselect("Target Project(s) (max 10)", target_project_list, format_func=lambda x: x[1])
    if len(target_projects_selected) > 10:
        st.error("You can select a maximum of 10 target projects.")
        return

    if st.button("Compare"):
        # Retrieve project details using the get_project_by_id method.
        source_details = source_auth.get_project_by_id(source_project[0])
        if not source_details:
            st.error("Failed to retrieve source project details.")
            return

        # Extract only the meta-level fields.
        source_meta = {
            "extractionModelId": source_details.get("extractionModelId"),
            "members": source_details.get("members"),
            "retentionDays": source_details.get("retentionDays"),
            "duplicates": source_details.get("duplicates"),
            "completion": source_details.get("completion"),
            "features": source_details.get("ocr", {}).get("features")
        }

        diff_list = []
        for target_proj in target_projects_selected:
            target_id, target_name = target_proj
            target_details = target_auth.get_project_by_id(target_id)
            if not target_details:
                st.warning(f"Failed to retrieve details for target project {target_name}.")
                continue

            target_meta = {
                "extractionModelId": target_details.get("extractionModelId"),
                "members": target_details.get("members"),
                "retentionDays": target_details.get("retentionDays"),
                "duplicates": target_details.get("duplicates"),
                "completion": target_details.get("completion"),
                "features": target_details.get("ocr", {}).get("features")
            }

            for field in source_meta:
                src_val = source_meta[field]
                tgt_val = target_meta.get(field)
                if src_val != tgt_val:
                    diff_list.append({
                        "Target Project": target_name,
                        "Field": field,
                        "Source Value": src_val,
                        "Target Value": tgt_val
                    })

        if diff_list:
            df = pd.DataFrame(diff_list, columns=["Target Project", "Field", "Source Value", "Target Value"])
            st.subheader("Meta Level Differences")
            st.dataframe(df)
        else:
            st.success("No differences found at the meta level.")            

def main():
    st.sidebar.title("Navigation")
    compare_option = st.sidebar.radio("Select Compare Mode", ["Compare Datapoints", "Compare Metadata"])
    
    # Always show the credentials input at the top.
    input_credentials()
    if st.button("Authenticate Credentials"):
        authenticate_credentials()
    
    if compare_option in ["Compare Metadata"]:
        # MetaLevel comparison option.
        compare_meta_level_section()
    else:
        # DatapoinLevel comparison option.
        compare_datapoints_option()

if __name__ == "__main__":
    main()
