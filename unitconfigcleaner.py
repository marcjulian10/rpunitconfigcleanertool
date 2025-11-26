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
    
    # Explicitly allow N/A variants
    if s_str.upper() in ['N/A', 'NA', '']:
        return False

    pattern = re.compile(r'[^a-zA-Z0-9\s-]')
    return bool(pattern.search(s_str))

def clean_field(value):
    """
    Standard cleaner for Tower and Corp fields.
    Returns empty string if value is N/A, NA, na, or blank.
    """
    if pd.isna(value):
        return ''
    
    val_str = str(value).strip()
    if val_str.lower() in ['n/a', 'na', '', 'blank']:
        return ''
    
    return val_str

# -------------------------------------------------
# UI Review Handlers
# -------------------------------------------------

def review_special_char_rows(df, file_key):
    decision_key = f"decision_spec_{file_key}"
    
    st.warning("⚠️ Special characters (e.g. dates, symbols) detected!")
    st.write("Review the rows below.")
    st.dataframe(df.head(50))

    if decision_key not in st.session_state:
        st.session_state[decision_key] = None

    def set_radio_spec():
        st.session_state[f"choice_spec_{file_key}"] = st.session_state[f"radio_spec_{file_key}"]

    st.radio(
        "Action for Special Characters:",
        ("Keep These Rows", "Delete These Rows", "Cancel Processing"),
        key=f"radio_spec_{file_key}",
        on_change=set_radio_spec
    )

    current_choice = st.session_state.get(f"choice_spec_{file_key}", "Keep These Rows")

    def set_decision_spec():
        st.session_state[decision_key] = {
            "Keep These Rows": "keep",
            "Delete These Rows": "delete",
            "Cancel Processing": "cancel"
        }.get(current_choice)

    if st.session_state[decision_key] is None:
        st.button("Confirm Special Chars", key=f"btn_spec_{file_key}", on_click=set_decision_spec)
        st.stop()
    
    return st.session_state[decision_key]


def review_duplicate_rows(df, file_key):
    """
    Handler for Duplicate Unit + Tower combinations
    """
    decision_key = f"decision_dup_{file_key}"
    
    st.warning("⚠️ Duplicate Unit & Tower combinations detected!")
    st.write("The following rows have identical Unit and Tower values:")
    st.dataframe(df.head(50))

    if decision_key not in st.session_state:
        st.session_state[decision_key] = None

    def set_radio_dup():
        st.session_state[f"choice_dup_{file_key}"] = st.session_state[f"radio_dup_{file_key}"]

    st.radio(
        "Action for Duplicates:",
        ("Keep All (2+ Rows)", "Retain 1 Row", "Cancel Processing"),
        key=f"radio_dup_{file_key}",
        on_change=set_radio_dup
    )

    current_choice = st.session_state.get(f"choice_dup_{file_key}", "Keep All (2+ Rows)")

    def set_decision_dup():
        st.session_state[decision_key] = {
            "Keep All (2+ Rows)": "keep",
            "Retain 1 Row": "retain_one",
            "Cancel Processing": "cancel"
        }.get(current_choice)

    if st.session_state[decision_key] is None:
        st.button("Confirm Duplicates", key=f"btn_dup_{file_key}", on_click=set_decision_dup)
        st.stop()
    
    return st.session_state[decision_key]

# -------------------------------------------------
# Main Cleaning Logic
# -------------------------------------------------

def clean_units_streamlit(file, file_key):
    result_key = f"result_{file_key}"
    
    if result_key in st.session_state:
        return st.session_state[result_key]

    try:
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
        # 1. Check Special Characters
        # -----------------------------------------
        special_char_mask = df[unit_col].apply(contains_special_chars)
        problem_rows = df[special_char_mask]
        deleted_rows_count = 0

        if not problem_rows.empty:
            st.subheader(f"Step 1: Special Characters ({file.name})")
            decision_spec = review_special_char_rows(problem_rows, file_key) 

            if decision_spec == "delete":
                df.drop(problem_rows.index, inplace=True)
                deleted_rows_count = len(problem_rows)
            elif decision_spec == "cancel":
                st.session_state[result_key] = f"🟡 Canceled processing for {file.name}."
                return st.session_state[result_key]

        # -----------------------------------------
        # 2. Check Duplicates (Unit + Tower)
        # -----------------------------------------
        # Create temp columns to strictly check duplicates ignoring whitespace
        df['__temp_unit'] = df[unit_col].apply(lambda x: str(x).strip())
        df['__temp_tower'] = df[tower_col].apply(clean_field) if tower_col else ''
        
        # Check for duplicates on these two columns
        dup_mask = df.duplicated(subset=['__temp_unit', '__temp_tower'], keep=False)
        dup_rows = df[dup_mask]
        
        duplicate_decision = "retain_one" # Default behavior if no duplicates found

        if not dup_rows.empty:
            st.divider()
            st.subheader(f"Step 2: Duplicates ({file.name})")
            duplicate_decision = review_duplicate_rows(dup_rows, file_key)

            if duplicate_decision == "retain_one":
                # Keep first, drop rest
                df.drop_duplicates(subset=['__temp_unit', '__temp_tower'], keep='first', inplace=True)
            elif duplicate_decision == "cancel":
                st.session_state[result_key] = f"🟡 Canceled processing for {file.name} (Duplicates)."
                return st.session_state[result_key]

        # -----------------------------------------
        # 3. Build Unit Strings (Always Concatenate)
        # -----------------------------------------
        # Refresh temp columns after potential drops
        df['__temp_unit'] = df[unit_col].apply(lambda x: str(x).strip())
        df['_CleanUnit'] = df['__temp_unit']
        
        def build_unit_unconditional(row):
            # 1. Gather raw values
            raw_unit = row['_CleanUnit']
            raw_tower = row[tower_col] if tower_col else ''
            raw_corp = row[corp_col] if corp_col else ''

            # 2. Clean values (removes N/A, Blank, NA, na)
            unit = clean_field(raw_unit) # Though unit usually shouldn't be NA if we got this far
            tower = clean_field(raw_tower)
            corp = clean_field(raw_corp)

            # 3. Concatenate non-empty parts
            parts = []
            
            # Add Tower first if exists
            if tower:
                parts.append(tower)
            
            # Add Unit (Essential)
            if unit:
                parts.append(unit)

            # Join with hyphens
            return " - ".join(parts)

        df['Unit'] = df.apply(build_unit_unconditional, axis=1)

        # -----------------------------------------
        # 4. Final Cleanup & Output
        # -----------------------------------------
        
        if duplicate_decision == "retain_one":
            df_unique = df.drop_duplicates(subset=['Unit']).reset_index(drop=True)
        else:
            df_unique = df.reset_index(drop=True)

        cols_to_drop = ['_CleanUnit', '__temp_unit', '__temp_tower']
        df_unique.drop(columns=[c for c in cols_to_drop if c in df_unique.columns], inplace=True)
        
        df_unique.replace({'N/A': '', 'n/a': '', 'na': '', '': ''}, inplace=True)

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
        result_message += f"🔢 Total Rows: {len(df_unique)}"

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
    # Clean up all possible session state keys for files
    for key in st.session_state['uploaded_files_keys']:
        suffixes = ['result', 'data', 'decision_spec', 'choice_spec', 'radio_spec', 
                    'decision_dup', 'choice_dup', 'radio_dup', 'output']
        for suf in suffixes:
            full_key = f"{suf}_{key}"
            if full_key in st.session_state:
                del st.session_state[full_key]
    
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

    st.info("Files are processed sequentially. You may be prompted to review special characters or duplicates.")
    
    results = []

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
