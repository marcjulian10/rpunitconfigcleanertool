
import streamlit as st
import pandas as pd
import re

# -----------------------------------------
# Helpers
# -----------------------------------------
def contains_special_chars(s):
    """Return True if s contains any character outside letters, digits, spaces, or hyphens."""
    if pd.isna(s):
        return False
    s_str = str(s).strip()
    # Ignore NA-like values
    if s_str.upper() in ['N/A', 'NA', 'n/a', 'na', '']:
        return False
    pattern = re.compile(r'[^a-zA-Z0-9\s\-]')
    return bool(pattern.search(s_str))

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
    """
    Tower allows ANY characters. We only normalize NA-like values to empty.
    """
    if tower_value is None:
        return ''
    s = str(tower_value).strip()
    if s.lower() in ['n/a', 'na', '']:
        return ''
    return s

# -----------------------------------------
# UI: Review Unit rows with special characters
# -----------------------------------------
def review_unit_special_rows(df_problem, file_key):
    """
    Show rows whose Unit contains special characters and let the user decide:
    Keep / Delete / Cancel.
    """
    decision_key = f"unit_sc_decision_{file_key}"
    st.warning("⚠️ Some rows have special characters in the **Unit** column.")
    st.write("Please review and choose an action.")
    st.dataframe(df_problem)

    if decision_key not in st.session_state:
        st.session_state[decision_key] = None

    def set_choice():
        st.session_state[f"unit_sc_choice_{file_key}"] = st.session_state[f"unit_sc_radio_{file_key}"]

    st.radio(
        "Action for rows with special characters in Unit:",
        ("Keep These Rows", "Delete These Rows", "Cancel Processing"),
        key=f"unit_sc_radio_{file_key}",
        on_change=set_choice
    )
    current_choice = st.session_state.get(f"unit_sc_choice_{file_key}", "Keep These Rows")

    def set_decision():
        st.session_state[decision_key] = {
            "Keep These Rows": "keep",
            "Delete These Rows": "delete",
            "Cancel Processing": "cancel"
        }.get(current_choice)
        st.rerun()

    if st.session_state[decision_key] is None:
        st.button("Confirm", key=f"unit_sc_confirm_{file_key}", on_click=set_decision)
        st.stop()

    return st.session_state[decision_key]

# -----------------------------------------
# UI: Review duplicates on (Tower, Unit)
# -----------------------------------------
def review_duplicate_units_towers(dupe_df, file_key):
    """
    When duplicates exist for the (Tower, Unit) pair, let the user choose:
    Keep all duplicates / Keep 1 per (Tower, Unit) / Cancel Processing.
    """
    dup_decision_key = f"dup_decision_{file_key}"
    st.warning("🟧 Duplicate combinations of **(Tower, Unit)** detected.")
    st.write("Review the duplicates below and choose how to handle them.")
    st.dataframe(dupe_df)

    if dup_decision_key not in st.session_state:
        st.session_state[dup_decision_key] = None

    def set_dup_choice():
        st.session_state[f"dup_choice_{file_key}"] = st.session_state[f"dup_radio_{file_key}"]

    st.radio(
        "Duplicate handling:",
        ("Keep all duplicates", "Keep 1 per (Tower, Unit)", "Cancel Processing"),
        key=f"dup_radio_{file_key}",
        on_change=set_dup_choice
    )
    current_choice = st.session_state.get(f"dup_choice_{file_key}", "Keep all duplicates")

    def set_dup_decision():
        st.session_state[dup_decision_key] = {
            "Keep all duplicates": "keep_all",
            "Keep 1 per (Tower, Unit)": "keep_one",
            "Cancel Processing": "cancel"
        }.get(current_choice)
        st.rerun()

    if st.session_state[dup_decision_key] is None:
        st.button("Confirm duplicate handling", key=f"dup_confirm_{file_key}", on_click=set_dup_decision)
        st.stop()

    return st.session_state[dup_decision_key]

# -----------------------------------------
# Main Cleaning Logic
# -----------------------------------------
def clean_units_streamlit(file, file_key):
    result_key = f"result_{file_key}"
    if result_key in st.session_state:
        return st.session_state[result_key]

    try:
        data_key = f"data_{file_key}"
        if data_key not in st.session_state:
            st.session_state[data_key] = read_file(file)
        df = st.session_state[data_key].copy()

        # Identify columns
        tower_col = next((c for c in df.columns if 'tower' in c.lower()), None)
        unit_col  = next((c for c in df.columns if 'unit'  in c.lower()), None)
        corp_col  = next((c for c in df.columns if 'corporate' in c.lower()), None)

        if not unit_col:
            st.session_state[result_key] = f"⚠️ No 'Unit' column found in {file.name}."
            return st.session_state[result_key]

        # --- Step 1: Special-char review on Unit only ---
        unit_sc_mask = df[unit_col].apply(contains_special_chars)
        unit_problem_rows = df[unit_sc_mask]
        deleted_sc_rows_count = 0

        if not unit_problem_rows.empty:
            st.subheader(f"File: {file.name}")
            decision = review_unit_special_rows(unit_problem_rows, file_key)
            if decision == "delete":
                df.drop(unit_problem_rows.index, inplace=True)
                deleted_sc_rows_count = len(unit_problem_rows)
            elif decision == "cancel":
                st.session_state[result_key] = f"🟡 Canceled processing for {file.name}."
                return st.session_state[result_key]
            # if "keep", proceed without changes

        # --- Step 2: Normalize and build display Unit ---
        df['_CleanUnit'] = df[unit_col].apply(lambda x: str(x).strip())
        def build_display_unit(row):
            unit  = row['_CleanUnit']
            tower = clean_tower(row[tower_col]) if tower_col else ''
            corp  = str(row[corp_col]).strip() if corp_col and pd.notna(row[corp_col]) else ''
            # Display string (same as your prior logic)
            if tower and corp:
                return f"{tower} - {unit}"
            elif tower:
                return f"{tower} - {unit}"
            else:
                return unit

        df['Unit'] = df.apply(build_display_unit, axis=1)

        # --- Step 3: Duplicate detection on the (Tower_clean, Unit_base) pair ---
        df['_TowerClean'] = df[tower_col].apply(clean_tower) if tower_col else ''
        df['_UnitBase']   = df['_CleanUnit']

        dup_mask = df.duplicated(subset=['_TowerClean', '_UnitBase'], keep=False)
        dup_df = df[dup_mask].copy()

        if not dup_df.empty:
            # Show relevant columns for review
            show_cols = ['Unit', unit_col] + ([tower_col] if tower_col else [])
            dup_decision = review_duplicate_units_towers(dup_df[show_cols], file_key)

            if dup_decision == "cancel":
                st.session_state[result_key] = f"🟡 Canceled processing for {file.name}."
                return st.session_state[result_key]
            elif dup_decision == "keep_one":
                # Keep only one row per (Tower_clean, Unit_base)
                df = df.drop_duplicates(subset=['_TowerClean', '_UnitBase'], keep='first')
            else:
                # keep_all: do nothing
                pass

        # --- Step 4: Cleanup helper columns & NA-like values ---
        for col in ['_CleanUnit', '_TowerClean', '_UnitBase']:
            if col in df.columns:
                df.drop(columns=[col], inplace=True)

        df.replace({'N/A': '', 'n/a': '', 'na': ''}, inplace=True)

        # --- Step 5: Output ---
        output = df.to_csv(index=False).encode('utf-8')
        st.session_state[f"output_{file_key}"] = output
        st.download_button(
            label=f"⬇️ Download Cleaned File ({file.name})",
            data=output,
            file_name=file.name.replace('.xlsx', '_cleaned.csv').replace('.csv', '_cleaned.csv'),
            mime='text/csv',
            key=f"download_{file_key}"
        )

        # --- Step 6: Result summary ---
        result_message = f"✅ Processed: {file.name}\n"
        if deleted_sc_rows_count > 0:
            result_message += f"🗑️ Deleted {deleted_sc_rows_count} row(s) due to special characters in **Unit**.\n"
        result_message += f"🔢 Total Rows Output: {len(df)}"
        st.session_state[result_key] = result_message
        return st.session_state[result_key]

    except Exception as e:
        st.session_state[result_key] = f"❌ Error processing {file.name}: {e}"
        return st.session_state[result_key]

# -----------------------------------------
# STREAMLIT UI
# -----------------------------------------
if 'uploaded_files_keys' not in st.session_state:
    st.session_state['uploaded_files_keys'] = []

st.title("🏢 Unit Configuration Cleaner Tool")

def handle_upload():
    keys_to_delete = []
    for key in st.session_state['uploaded_files_keys']:
        keys_to_delete.extend([
            f'result_{key}', f'data_{key}',
            f'unit_sc_decision_{key}', f'unit_sc_choice_{key}',
            f'dup_decision_{key}', f'dup_choice_{key}',
            f'output_{key}'
        ])
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
    st.info(
        "Scroll down as each file will be processed one-by-one. "
        "Processing will pause for your decisions on Unit special characters and duplicates."
    )

    for i, file_key in enumerate(st.session_state['uploaded_files_keys']):
        file = uploaded_files[i]
        is_processed = f"result_{file_key}" in st.session_state
        if not is_processed:
            st.divider()
            st.header(f"📄 Processing File {i+1}: **{file.name}**")
            clean_units_streamlit(file, file_key)

    st.divider()
    st.subheader("📌 Results Summary")
    for i, file_key in enumerate(st.session_state['uploaded_files_keys']):
        if f"result_{file_key}" in st.session_state:
            st.write(st.session_state[f"result_{file_key}"])
