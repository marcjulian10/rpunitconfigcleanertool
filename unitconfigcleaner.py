import streamlit as st
import pandas as pd
import os
import re
from io import StringIO, BytesIO

# -------------------------------------------------
# File Reading & Helper Functions
# -------------------------------------------------

def read_file(file):
    filename = file.name.lower()

    if filename.endswith('.xlsx'):
        return pd.read_excel(file, dtype=str, keep_default_na=False, engine='openpyxl')
    elif filename.endswith('.csv'):
        try:
            return pd.read_csv(file, dtype=str, keep_default_na=False, encoding='utf-8')
        except UnicodeDecodeError:
            file.seek(0)
            return pd.read_csv(file, dtype=str, keep_default_na=False, encoding='latin-1')
    else:
        raise ValueError(f"Unsupported file format for {filename}. Please use .csv or .xlsx")


def clean_tower(tower_value):
    # We still treat N/A as empty for the purpose of building the string (e.g. "Tower - Unit"), 
    # but we don't flag the row as an error anymore.
    if not tower_value or str(tower_value).strip().lower() in ['n/a', 'na', '', 'N/A']:
        return ''
    return str(tower_value).strip()

# -------------------------------------------------
# Main Cleaning Logic (Streamlined)
# -------------------------------------------------

def clean_units_streamlit(file, file_key):
    result_key = f"result_{file_key}"
    
    # If already processed, return cached result
    if result_key in st.session_state:
        return st.session_state[result_key]

    try:
        # Read Data
        df = read_file(file)

        # Identify Columns
        tower_col = next((c for c in df.columns if 'tower' in c.lower()), None)
        unit_col = next((c for c in df.columns if 'unit' in c.lower()), None)
        corp_col = next((c for c in df.columns if 'corporate' in c.lower()), None)

        if not unit_col:
            st.session_state[result_key] = f"⚠️ No 'Unit' column found in {file.name}."
            return st.session_state[result_key]

        # -----------------------------------------
        # Logic: Build Unique Unit String
        # -----------------------------------------
        
        # Create a temp clean column for duplicate detection
        df['_CleanUnit'] = df[unit_col].apply(lambda x: str(x).strip())
        
        # Identify duplicates based strictly on the Unit name
        duplicate_units = df[df.duplicated('_CleanUnit', keep=False)]

        def build_unit(row):
            unit = row['_CleanUnit']
            tower = clean_tower(row[tower_col]) if tower_col else ''
            corp = str(row[corp_col]).strip() if corp_col and pd.notna(row[corp_col]) else ''

            # If this unit name appears multiple times in the file, we append Tower/Corp info to make it unique
            if unit in duplicate_units['_CleanUnit'].values:
                same_unit_rows = duplicate_units[duplicate_units['_CleanUnit'] == unit]
                unique_towers = same_unit_rows[tower_col].dropna().apply(clean_tower).unique()

                # Logic: Combine Tower/Unit/Corp based on available data to create uniqueness
                if tower and len(unique_towers) > 1:
                    return f"{tower} - {unit}"
                elif tower and corp:
                    return f"{tower} - {unit} - {corp}"
                elif tower:
                    return f"{tower} - {unit}"
                else:
                    return unit
            else:
                # No duplicate unit name? Just return the unit name.
                return unit

        # Apply the logic
        df['Unit'] = df.apply(build_unit, axis=1)

        # Deduplicate the final dataframe
        df_unique = df.drop_duplicates(subset=['Unit']).reset_index(drop=True)
        df_unique = df_unique.drop_duplicates()
        
        # Cleanup
        if '_CleanUnit' in df_unique.columns:
            df_unique.drop(columns=['_CleanUnit'], inplace=True)
        
        # Ensure N/A strings are empty in the final output for cleanliness
        df_unique.replace({'N/A': '', 'n/a': '', 'na': '', '': ''}, inplace=True)

        # Prepare Download
        output = df_unique.to_csv(index=False).encode('utf-8')
        st.session_state[f"output_{file_key}"] = output

        # Show Download Button
        st.download_button(
            label=f"⬇️ Download Cleaned File ({file.name})",
            data=output,
            file_name=file.name.replace('.xlsx', '_cleaned.csv').replace('.csv', '_cleaned.csv'),
            mime='text/csv',
            key=f"download_{file_key}"
        )

        result_message = f"✅ Processed: {file.name}\n"
        result_message += f"🔢 Total Unique Units: {len(df_unique)}"

        st.session_state[result_key] = result_message
        return st.session_state[result_key]

    except Exception as e:
        st.session_state[result_key] = f"❌ Error processing {file.name}: {e}"
        return st.session_state[result_key]


# -------------------------------------------------
# STREAMLIT UI
# -------------------------------------------------

if 'uploaded_files_keys' not in st.session_state:
    st.session_state['uploaded_files_keys'] = []

st.title("🏢 Unit Configuration Cleaner Tool")

def handle_upload():
    # Clear previous results when new files are uploaded/changed
    keys_to_delete = []
    for key in st.session_state['uploaded_files_keys']:
        keys_to_delete.extend([f'result_{key}', f'output_{key}'])

    for key in keys_to_delete:
        if key in st.session_state:
            del st.session_state[key]
    
    if st.session_state.uploaded_files_widget:
        st.session_state['uploaded_files_keys'] = [f"file_{i}" for i in range(len(st.session_state.uploaded_files_widget))]
    else:
         st.session_state['uploaded_files_keys'] = []

    
uploaded_files = st.file_uploader(
    "Select Excel or CSV Files",
    type=['xlsx', 'csv'],
    accept_multiple_files=True,
    key='uploaded_files_widget',
    on_change=handle_upload
)

if uploaded_files:
    if len(st.session_state['uploaded_files_keys']) != len(uploaded_files):
        st.session_state['uploaded_files_keys'] = [f"file_{i}" for i in range(len(uploaded_files))]
    
    results = []

    # Loop through the files
    for i, file_key in enumerate(st.session_state['uploaded_files_keys']):
        file = uploaded_files[i]
        
        is_processed = f"result_{file_key}" in st.session_state
        
        if not is_processed:
            st.divider()
            st.header(f"📄 Processing File {i+1}: **{file.name}**")
        
        result = clean_units_streamlit(file, file_key)
        results.append(result)

    st.divider()
    st.subheader("📌 Results Summary")
    
    for i, file_key in enumerate(st.session_state['uploaded_files_keys']):
        if f"result_{file_key}" in st.session_state:
             st.write(st.session_state[f"result_{file_key}"])
