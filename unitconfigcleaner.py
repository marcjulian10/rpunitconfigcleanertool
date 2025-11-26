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

def contains_special_chars(s):
    if pd.isna(s):
        return False
    
    s_str = str(s).strip()
    
    # Explicitly allow N/A variants so they don't trigger the warning
    if s_str.upper() in ['N/A', 'NA', '']:
        return False

    # Flag anything that is NOT a letter, number, space, or hyphen
    # This will catch '/' (dates), '$', '#', '@', etc.
    pattern = re.compile(r'[^a-zA-Z0-9\s-]')
    return bool(pattern.search(s_str))

def clean_tower(tower_value):
    if not tower_value or str(tower_value).strip().lower() in ['n/a', 'na', '', 'N/A']:
        return ''
    return str(tower_value).strip()

# -------------------------------------------------
# Review Handler (Restored & Improved)
# -------------------------------------------------

def review_special_char_rows(df, file_key):
    """
    Handles user decision for special character rows using session state.
    """
    decision_key = f"decision_{file_key}"
    
    st.warning("⚠️ Special characters (e.g. dates with slashes, symbols) detected in this file!")
    st.write("Review the rows below. N/A values are ignored and considered safe.")

    # Show a sample of the problematic rows
    st.dataframe(df.head(100))
    if len(df) > 100:
        st.write(f"...and {len(df) - 100} more rows.")

    if decision_key not in st.session_state:
        st.session_state[decision_key] = None

    # Callback to sync radio button with decision
    def set_radio_choice():
        st.session_state[f"choice_{file_key}"] = st.session_state[f"radio_{file_key}"]

    st.radio(
        "Select an action:",
        ("Keep These Rows", "Delete These Rows", "Cancel Processing"),
        key=f"radio_{file_key}",
        on_change=set_radio_choice
    )

    # Get current choice (default to Keep)
    current_choice = st.session_state.get(f"choice_{file_key}", "Keep These Rows")

    def set_decision():
        st.session_state[decision_key] = {
            "Keep These Rows": "keep",
            "Delete These Rows": "delete",
            "Cancel Processing": "cancel"
        }.get(current_choice)
        # No rerun here, let the script flow continue or stop naturally next cycle
        
    if st.session_state[decision_key] is None:
        st.button("Confirm Choice", key=f"confirm_{file_key}", on_click=set_decision)
        st.stop() # Halt execution until button is clicked
    
    return st.session_state[decision_key]

# -------------------------------------------------
# Main Cleaning Logic
# -------------------------------------------------

def clean_units_streamlit(file, file_key):
    result_key = f"result_{file_key}"
    
    if result_key in st.session_state:
        return st.session_state[result_key]

    try:
        # We store the raw dataframe in session state so we don't re-read the file on every interaction
        data_key = f"data_{file_key}"
        if data_key not in st.session_state:
            st.session_state[data_key] = read_file(file)

        df = st.session_state[data_key].copy()

        # Identify Columns
        tower_col = next((c for c in df.columns if 'tower' in c.lower()), None)
        unit_col = next((c for c in df.columns if 'unit' in c.lower()), None)
        corp_col = next((c for c in df.columns if 'corporate' in c.lower()), None)

        if not unit_col:
            st.session_state[result_key] = f"⚠️ No 'Unit' column found in {file.name}."
            return st.session_state[result_key]

        # -----------------------------------------
        # Check for Special Characters (Dates/Symbols)
        # -----------------------------------------
        # We only check the Unit column for special characters as that is the critical identifier
        special_char_mask = df[unit_col].apply(contains_special_chars)
        problem_rows = df[special_char_mask]
        deleted_rows_count = 0

        if not problem_rows.empty:
            st.subheader(f"File: {file.name}")
            decision = review_special_char_rows(problem_rows, file_key) 

            if decision == "delete":
                df.drop(problem_rows.index, inplace=True)
                deleted_rows_count = len(problem_rows)
            elif decision == "cancel":
                st.session_state[result_key] = f"🟡 Canceled processing for {file.name}."
                return st.session_state[result_key]
            # If "keep", we just proceed without changes

        # -----------------------------------------
        # Logic: Build Unique Unit String
        # -----------------------------------------
        
        df['_CleanUnit'] = df[unit_col].apply(lambda x: str(x).strip())
        duplicate_units = df[df.duplicated('_CleanUnit', keep=False)]

        def build_unit(row):
            unit = row['_CleanUnit']
            tower = clean_tower(row[tower_col]) if tower_col else ''
            corp = str(row[corp_col]).strip() if corp_col and pd.notna(row[corp_col]) else ''

            if unit in duplicate_units['_CleanUnit'].values:
                same_unit_rows = duplicate_units[duplicate_units['_CleanUnit'] == unit]
                unique_towers = same_unit_rows[tower_col].dropna().apply(clean_tower).unique()

                if tower and len(unique_towers) > 1:
                    return f"{tower} - {unit}"
                elif tower and corp:
                    return f"{tower} - {unit} - {corp}"
                elif tower:
                    return f"{tower} - {unit}"
                else:
                    return unit
            else:
                return unit

        df['Unit'] = df.apply(build_unit, axis=1)

        # Deduplicate
        df_unique = df.drop_duplicates(subset=['Unit']).reset_index(drop=True)
        df_unique = df_unique.drop_duplicates()
        
        if '_CleanUnit' in df_unique.columns:
            df_unique.drop(columns=['_CleanUnit'], inplace=True)
        
        df_unique.replace({'N/A': '', 'n/a': '', 'na': '', '': ''}, inplace=True)

        # Output
        output = df_unique.to_csv(index=False).encode('utf-8')
        st.session_state[f"output_{file_key}"] = output

        st.download_button(
            label=f"⬇️ Download Cleaned File ({file.name})",
            data=output,
            file_name=file.name.replace('.xlsx', '_cleaned.csv').replace('.csv', '_cleaned.csv'),
            mime='text/csv',
            key=f"download_{file_key}"
        )

        result_message = f"✅ Processed: {file.name}\n"
        if deleted_rows_count > 0:
            result_message += f"🗑️ Deleted {deleted_rows_count} rows with special characters.\n"
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
    keys_to_delete = []
    for key in st.session_state['uploaded_files_keys']:
        keys_to_delete.extend([f'result_{key}', f'data_{key}', f'decision_{key}', f'choice_{key}', f'output_{key}', f'radio_{key}'])

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

    st.info("Files are processed sequentially. If a file requires review, please select an option and click Confirm.")
    
    results = []

    for i, file_key in enumerate(st.session_state['uploaded_files_keys']):
        file = uploaded_files[i]
        
        is_processed = f"result_{file_key}" in st.session_state
        
        if not is_processed:
            st.divider()
            st.header(f"📄 Processing File {i+1}: **{file.name}**")
        
        # This function calls st.stop() if user input is needed
        result = clean_units_streamlit(file, file_key)
        results.append(result)

    st.divider()
    st.subheader("📌 Results Summary")
    
    for i, file_key in enumerate(st.session_state['uploaded_files_keys']):
        if f"result_{file_key}" in st.session_state:
             st.write(st.session_state[f"result_{file_key}"])
