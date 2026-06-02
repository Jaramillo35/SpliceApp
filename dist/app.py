from __future__ import annotations

from pathlib import Path
import tempfile

import streamlit as st

from wiring_harness_processor import run_analysis


st.set_page_config(page_title="Wiring Harness Splice Generator", layout="wide")

st.title("⚡ Wiring Harness Splice Generator")
st.caption("✨ Generate harness print-ready direct connections, splices, configuration groups, and validation reports.")

uploaded_file = st.file_uploader("Upload Excel file (Complexity + OptionPerCkt)", type=["xlsx", "xls"])

if uploaded_file is None:
    st.info("Upload Input.xlsx (or equivalent) to begin analysis.")
    st.stop()

with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as temp_file:
    temp_file.write(uploaded_file.getbuffer())
    temp_path = temp_file.name

try:
    result = run_analysis(temp_path)
except Exception as exc:
    st.error(f"Analysis failed: {exc}")
    st.stop()

st.subheader("📊 Input Previews")
left, right = st.columns(2)
with left:
    st.markdown("**📋 Complexity Matrix (normalized)**")
    st.dataframe(result["harness_code_map_df"], use_container_width=True)
with right:
    st.markdown("**📋 OptionPerCircuit (normalized)**")
    st.dataframe(result["option_df"], use_container_width=True)

st.subheader("⚙️ Generated Configurations")
st.dataframe(result["configurations_df"], use_container_width=True)

st.subheader("🔗 Generated Connections")
# Group connections by circuit and configuration
conns_df = result["generated_connections_df"]
configs_df = result["configurations_df"]

# Create lookup for configuration details
config_lookup = {}
for _, cfg in configs_df.iterrows():
    key = (cfg["Circuit Name"], cfg["Configuration ID"])
    config_lookup[key] = {
        "topology_type": cfg["Topology Type"],
        "target_harness_pns": cfg["Target Harness PNs"],
    }

# Group by circuit and configuration
for (circuit, config_id), group in conns_df.groupby(["Circuit Name", "Configuration"], sort=False):
    cfg_details = config_lookup.get((circuit, config_id), {})
    topology = cfg_details.get("topology_type", "Unknown")
    target_pns = cfg_details.get("target_harness_pns", "")
    
    # Display circuit heading if this is the first config for this circuit
    if config_id == conns_df[conns_df["Circuit Name"] == circuit]["Configuration"].iloc[0]:
        st.markdown(f"### 📌 Circuit {circuit}")
    
    # Topology icon
    topo_icon = "📍" if topology == "Direct" else "🔀"
    st.markdown(f"**{topo_icon} Configuration {config_id} — {topology}**")
    
    # Summary info
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"🔗 **Connections:** {len(group)}")
    with col2:
        st.markdown(f"🏗️ **Topology:** {topology}")
    with col3:
        st.markdown(f"📦 **Target PNs:** {target_pns}")
    
    st.dataframe(group, use_container_width=True)
    st.markdown("---")

st.subheader("🔍 Device Evaluation")
st.dataframe(result["device_evaluation_df"], use_container_width=True)

st.subheader("📊 Harness Print Matrix")
st.markdown("Engineering applicability matrix showing which connections apply to each Harness PN:")
st.dataframe(result["harness_print_matrix_df"], use_container_width=True)

st.subheader("✅ Validation Report")
st.dataframe(result["validation_report_df"], use_container_width=True)

st.download_button(
    label="📥 Download Output Excel",
    data=result["output_excel_bytes"],
    file_name="Wiring_Harness_Output.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
