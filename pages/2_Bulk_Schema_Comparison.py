import streamlit as st
import pandas as pd
from deepdiff import DeepDiff
import json
from io import BytesIO
from auth import HypatosAPI
from helpers import get_datapoints_dict, get_metadata

st.set_page_config(page_title="Bulk Schema Comparison", layout="wide")

st.title("📊 Bulk Schema Comparison")
st.markdown("---")

# Initialize session state
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'source_api' not in st.session_state:
    st.session_state.source_api = None
if 'target_api' not in st.session_state:
    st.session_state.target_api = None
if 'comparison_results' not in st.session_state:
    st.session_state.comparison_results = None

# Helper function to load Excel with preserved formatting
def load_excel_table(uploaded_file: BytesIO) -> pd.DataFrame:
    """
    Reads Excel strictly as strings to preserve leading zeros and Excel's leading apostrophe.
    """
    df = pd.read_excel(
        uploaded_file,
        dtype=str,
        keep_default_na=False,
        engine="openpyxl"
    )
    # Normalize headers
    df.columns = [str(c).strip() for c in df.columns]
    
    def _normalize(val):
        if val is None:
            return ""
        s = str(val).strip()
        # Remove Excel's leading apostrophe for numbers like '00001
        if s.startswith("'") and len(s) > 1 and s[1:].replace(".", "").replace("-", "").isdigit():
            return s[1:]
        return s
    
    return df.applymap(_normalize)

def create_template_excel(sample_data: list) -> bytes:
    """Create an Excel template with sample data."""
    df = pd.DataFrame(sample_data)
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="Project Pairs")
    return bio.getvalue()

# Authentication Section
st.header("🔐 Authentication")

# URL Configuration
url_options = {
    "EU": "https://api.cloud.hypatos.ai/v2",
    "US": "https://api.cloud.hypatos.com/v2"
}

col1, col2 = st.columns(2)

with col1:
    st.subheader("Source Company")
    source_region = st.selectbox("Source Region", ["EU", "US"], key="source_region")
    source_url = url_options[source_region]
    st.text_input("Source URL", value=source_url, disabled=True, key="bulk_source_url_display")
    source_client_id = st.text_input("Source Client ID", key="bulk_source_client_id")
    source_client_secret = st.text_input("Source Client Secret", type="password", key="bulk_source_client_secret")

with col2:
    st.subheader("Target Company")
    target_region = st.selectbox("Target Region", ["EU", "US"], key="target_region")
    target_url = url_options[target_region]
    st.text_input("Target URL", value=target_url, disabled=True, key="bulk_target_url_display")
    target_client_id = st.text_input("Target Client ID", key="bulk_target_client_id")
    target_client_secret = st.text_input("Target Client Secret", type="password", key="bulk_target_client_secret")

if st.button("🔑 Authenticate Credentials", type="primary"):
    try:
        with st.spinner("Authenticating..."):
            # Create API instances with selected URLs
            source_api = HypatosAPI(source_client_id, source_client_secret, source_url)
            target_api = HypatosAPI(target_client_id, target_client_secret, target_url)
            
            # Authenticate both
            source_auth_success = source_api.authenticate()
            target_auth_success = target_api.authenticate()
            
            if source_auth_success and target_auth_success:
                st.session_state.source_api = source_api
                st.session_state.target_api = target_api
                st.session_state.authenticated = True
                st.success("✅ Authentication successful!")
            else:
                if not source_auth_success:
                    st.error("❌ Source authentication failed")
                if not target_auth_success:
                    st.error("❌ Target authentication failed")
                st.session_state.authenticated = False
    except Exception as e:
        st.error(f"❌ Authentication failed: {str(e)}")
        st.session_state.authenticated = False

st.markdown("---")

def compare_datapoints_detailed(source_flat, target_flat):
    """
    Compares flattened datapoints in detail, checking multiple attributes.
    Returns a list of differences.
    """
    differences = []
    all_keys = set(source_flat.keys()).union(set(target_flat.keys()))
    attributes = ["internalName", "displayName", "type", "rules", "normalization", "derivation", "source"]
    
    for key in all_keys:
        if key not in target_flat:
            differences.append({
                "Data Point": key,
                "Attribute": "Entire datapoint",
                "Difference": "Missing in target"
            })
        elif key not in source_flat:
            differences.append({
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
                        "Data Point": key,
                        "Attribute": attr,
                        "Difference": str(diff)
                    })
    return differences

def compare_metadata_detailed(source_meta, target_meta):
    """
    Compares metadata dictionaries field by field.
    Returns a list of differences.
    """
    differences = []
    for field in source_meta:
        src_val = source_meta[field]
        tgt_val = target_meta.get(field)
        if src_val != tgt_val:
            differences.append({
                "Field": field,
                "Source Value": str(src_val),
                "Target Value": str(tgt_val)
            })
    return differences

# File Upload and Comparison Section
if st.session_state.authenticated:
    st.header("📁 Upload Project Pairs")
    
    # Template Download Section
    st.subheader("📥 Download Template")
    st.info("Download the template file, fill in your project pairs, then upload it below.")
    
    # Sample data for template
    sample_data = [
        {"Source Project ID": "project-123-example", "Target Project ID": "project-456-example"},
        {"Source Project ID": "project-789-example", "Target Project ID": "project-012-example"},
        {"Source Project ID": "project-345-example", "Target Project ID": "project-678-example"}
    ]
    
    template_excel = create_template_excel(sample_data)
    st.download_button(
        label="📄 Download Template",
        data=template_excel,
        file_name="project_pairs_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Template with example project IDs"
    )
    
    st.markdown("---")
    
    # File Upload Section
    st.subheader("📤 Upload Your File")
    
    st.info("""
    **File Format Requirements:**
    - Upload an Excel file (.xlsx or .xls)
    - **Column 1:** Source Project IDs
    - **Column 2:** Target Project IDs
    - Each row represents one comparison pair
    - Leading zeros in project IDs will be preserved automatically
    """)
    
    uploaded_file = st.file_uploader(
        "Choose an Excel file", 
        type=['xlsx', 'xls'],
        help="Upload an Excel file with Source and Target project IDs in two columns"
    )
    
    if uploaded_file is not None:
        try:
            # Read the Excel file with proper formatting preservation
            df = load_excel_table(uploaded_file)
            
            # Display the uploaded data
            st.subheader("📋 Uploaded Project Pairs")
            
            # Ensure we have at least 2 columns
            if df.shape[1] < 2:
                st.error("❌ File must have at least 2 columns (Source and Target project IDs)")
            else:
                # Use first two columns regardless of their names
                df_display = df.iloc[:, :2].copy()
                df_display.columns = ['Source Project ID', 'Target Project ID']
                
                # Remove any rows with missing values
                df_display = df_display.dropna()
                df_display = df_display[
                    (df_display['Source Project ID'] != '') & 
                    (df_display['Target Project ID'] != '')
                ]
                
                if len(df_display) == 0:
                    st.error("❌ No valid project pairs found in the file")
                else:
                    st.dataframe(df_display, use_container_width=True)
                    st.caption(f"Total pairs to compare: {len(df_display)}")
                    
                    # Comparison type selection
                    comparison_type = st.radio(
                        "Select Comparison Type:",
                        ["Data Points", "Metadata"],
                        horizontal=True
                    )
                    
                    # Compare button
                    if st.button("🔍 Compare All Pairs", type="primary"):
                        results = []
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        total_pairs = len(df_display)
                        
                        for idx, row in df_display.iterrows():
                            source_project_id = str(row['Source Project ID']).strip()
                            target_project_id = str(row['Target Project ID']).strip()
                            
                            status_text.text(f"Comparing pair {idx + 1}/{total_pairs}: {source_project_id} → {target_project_id}")
                            
                            # Initialize project names
                            source_project_name = source_project_id
                            target_project_name = target_project_id
                            
                            try:
                                # Fetch project names
                                try:
                                    source_project_details = st.session_state.source_api.get_project_by_id(source_project_id)
                                    if source_project_details:
                                        source_project_name = source_project_details.get('name', source_project_id)
                                except:
                                    pass  # Keep ID as name if fetch fails
                                
                                try:
                                    target_project_details = st.session_state.target_api.get_project_by_id(target_project_id)
                                    if target_project_details:
                                        target_project_name = target_project_details.get('name', target_project_id)
                                except:
                                    pass  # Keep ID as name if fetch fails
                                
                                if comparison_type == "Data Points":
                                    # Get flattened datapoints for both projects
                                    source_datapoints = get_datapoints_dict(
                                        st.session_state.source_api, 
                                        source_project_id
                                    )
                                    target_datapoints = get_datapoints_dict(
                                        st.session_state.target_api, 
                                        target_project_id
                                    )
                                    
                                    # Detailed comparison
                                    differences = compare_datapoints_detailed(source_datapoints, target_datapoints)
                                    
                                else:  # Metadata
                                    # Get metadata for both projects
                                    source_metadata = get_metadata(
                                        st.session_state.source_api, 
                                        source_project_id
                                    )
                                    target_metadata = get_metadata(
                                        st.session_state.target_api, 
                                        target_project_id
                                    )
                                    
                                    # Detailed comparison
                                    differences = compare_metadata_detailed(source_metadata, target_metadata)
                                
                                results.append({
                                    'source_project_id': source_project_id,
                                    'source_project_name': source_project_name,
                                    'target_project_id': target_project_id,
                                    'target_project_name': target_project_name,
                                    'has_differences': len(differences) > 0,
                                    'differences': differences,
                                    'error': None
                                })
                                
                            except Exception as e:
                                results.append({
                                    'source_project_id': source_project_id,
                                    'source_project_name': source_project_name,
                                    'target_project_id': target_project_id,
                                    'target_project_name': target_project_name,
                                    'has_differences': None,
                                    'differences': [],
                                    'error': str(e)
                                })
                            
                            progress_bar.progress((idx + 1) / total_pairs)
                        
                        status_text.text("✅ Comparison complete!")
                        st.session_state.comparison_results = {
                            'results': results,
                            'comparison_type': comparison_type
                        }
        
        except Exception as e:
            st.error(f"❌ Error reading file: {str(e)}")

    st.markdown("---")
    
    # Display Results
    if st.session_state.comparison_results is not None:
        st.header("📊 Comparison Results")
        
        results = st.session_state.comparison_results['results']
        comparison_type = st.session_state.comparison_results['comparison_type']
        
        # Summary statistics
        col1, col2, col3 = st.columns(3)
        
        total = len(results)
        successful = len([r for r in results if r['error'] is None])
        with_differences = len([r for r in results if r['has_differences'] == True])
        identical = len([r for r in results if r['has_differences'] == False])
        
        col1.metric("Total Comparisons", total)
        col2.metric("With Differences", with_differences)
        col3.metric("Identical", identical)
        
        if successful < total:
            st.warning(f"⚠️ {total - successful} comparison(s) failed")
        
        st.markdown("---")
        
        # Detailed results for each pair
        for idx, result in enumerate(results):
            status_icon = "✅" if result['has_differences'] == False else "⚠️" if result['error'] is None else "❌"
            status_text = "Identical" if result['has_differences'] == False else "Differences Found" if result['error'] is None else "Error"
            
            # Create display title with project names
            source_display = f"{result['source_project_name']}" if result['source_project_name'] != result['source_project_id'] else result['source_project_id']
            target_display = f"{result['target_project_name']}" if result['target_project_name'] != result['target_project_id'] else result['target_project_id']
            
            with st.expander(
                f"**Pair {idx + 1}:** {source_display} → {target_display} ({status_text} {status_icon})",
                expanded=(result['has_differences'] == True)
            ):
                if result['error']:
                    st.error(f"Error during comparison: {result['error']}")
                else:
                    # Display project info in a nice format
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**Source Project**")
                        st.markdown(f"**Name:** {result['source_project_name']}")
                        st.markdown(f"**ID:** `{result['source_project_id']}`")
                    with col2:
                        st.markdown("**Target Project**")
                        st.markdown(f"**Name:** {result['target_project_name']}")
                        st.markdown(f"**ID:** `{result['target_project_id']}`")
                    
                    if not result['has_differences']:
                        st.success(f"✅ The {comparison_type.lower()} are identical!")
                    else:
                        st.warning(f"⚠️ {len(result['differences'])} difference(s) found in {comparison_type.lower()}")
                        
                        # Display differences in a table
                        if result['differences']:
                            diff_df = pd.DataFrame(result['differences'])
                            st.dataframe(diff_df, use_container_width=True)
        
        # Export results option
        st.markdown("---")
        st.subheader("💾 Export Results")
        
        # Create summary dataframe
        summary_data = []
        for result in results:
            summary_data.append({
                'Source Project Name': result['source_project_name'],
                'Source Project ID': result['source_project_id'],
                'Target Project Name': result['target_project_name'],
                'Target Project ID': result['target_project_id'],
                'Status': 'Error' if result['error'] else ('Identical' if not result['has_differences'] else 'Differences Found'),
                'Number of Differences': 0 if result['error'] else len(result['differences']),
                'Error Message': result['error'] if result['error'] else ''
            })
        
        summary_df = pd.DataFrame(summary_data)
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Export summary as Excel
            summary_excel = create_template_excel(summary_data)
            st.download_button(
                label="📥 Download Summary (Excel)",
                data=summary_excel,
                file_name="schema_comparison_summary.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        
        with col2:
            # Create detailed JSON export
            detailed_export = {
                'comparison_type': comparison_type,
                'total_comparisons': total,
                'successful_comparisons': successful,
                'with_differences': with_differences,
                'identical': identical,
                'results': results
            }
            
            json_str = json.dumps(detailed_export, indent=2, default=str)
            st.download_button(
                label="📥 Download Detailed Results (JSON)",
                data=json_str,
                file_name="schema_comparison_detailed.json",
                mime="application/json"
            )

else:
    st.info("👆 Please authenticate with both source and target company credentials to continue.")
