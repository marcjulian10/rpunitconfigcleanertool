import streamlit as st
import pandas as pd
import os
import re
from io import StringIO, BytesIO

# -------------------------------------------------
# Original Logic (unchanged)
# -------------------------------------------------

def contains_special_chars(s):
    if pd.isna(s):
        return False

    pattern = re.compile(r'[^a-zA-Z0-9\s-]')
    return bool(pattern.search(str(s)))


def read_file(file):
    filename = file.name.lower()

    if filename.endswith('.xlsx'):
        return pd.read_excel(file, dtype=str, keep_default_na=False, engine='openpyxl')
    elif filename.endswith('.csv'):
        # For CSV, try reading with 'utf-8' encoding first, then fall back to 'latin-1'
        try:
            return pd.read_csv(file, dtype=str, keep_default_na=False, encoding='utf-8')
        except UnicodeDecodeError:
            file.seek(0) # Reset file pointer for the next read attempt
            return pd.read_csv(file, dtype=str, keep_default_na=False, encoding='latin-1')
    else:
        raise ValueError(f"Unsupported file format for {filename}. Please use .csv or .xlsx")


def clean_tower(tower_value):
    if not tower_value or str(tower_value).strip().lower() in ['n/a', 'na', '', 'N/A']:
        return ''
    return str(tower_value).strip()


# -------------------------------------------------
# STREAMLIT SPECIAL CHARACTER REVIEW HANDLER (Modified for Session State)
# -------------------------------------------------

def review_special_char_rows(df, file_key):
    """
    Handles user decision for special character rows using session state.
    
    Returns the decision ('keep', 'delete', 'cancel') or None if pending.
    """
    decision_key = f"decision_{file_key}"
    
    st.warning("⚠️ Special characters detected in this file!")
    st.write("Choose whether to keep or delete the rows before continuing.")

    st.dataframe(df)

    # Initialize session state for the decision if not present
    if decision_key not in st.session_state:
        st.session_state[decision_key] = None

    # Use a callback function to capture the radio button change
    def set_radio_choice():
        st.session_state[f"choice_{file_key}"] = st.session_state[f"radio_{file_key}"]

    st.radio(
        "Select an action:",
        ("Keep These Rows", "Delete These Rows", "Cancel Processing"),
        key=f"radio_{file_key}",
        on_change=set_radio_choice
    )

    # The choice defaults to the first option if the radio has never been clicked
    current_choice = st.session_state.get(f"choice_{file_key}", "Keep These Rows")

    def set_decision():
        # Set the final decision on button click
        st.session_state[decision_key] = {
            "Keep These Rows": "keep",
            "Delete These Rows": "delete",
            "Cancel Processing": "cancel"
        }.get(current_choice)
        
        # FIX: Use st.rerun() instead of the deprecated st.experimental_rerun()
        st.rerun() 

    # Only show the button if a decision is pending
    if st.session_state[decision_key] is None:
        st.button("Confirm", key=f"confirm_{file_key}", on_click=set_decision)
        # Stop processing here, waiting for the button click to set the decision
        st.stop()
    
    # Return the saved decision
    return st.session_state[decision_key]


# -------------------------------------------------
# Main Cleaning Logic (Modified for Session State)
# -------------------------------------------------

def clean_units_streamlit(file, file_key):
    # Use session state to store and retrieve the final result message
    result_key = f"result_{file_key}"
    
    # 1. Check if processing is complete for this file
    if result_key in st.session_state:
        return st.session_state[result_key]

    try:
        # Load the file content into session state to survive reruns
        data_key = f"data_{file_key}"
        if data_key not in st.session_state:
            st.session_state[data_key] = read_file(file)

        df = st.session_state[data_key].copy()
        
        special_char_mask = df.apply(
            lambda row: row.astype(str).apply(contains_special_chars).any(),
            axis=1
        )

        problem_rows = df[special_char_mask]
        deleted_rows_count = 0

        # 2. Special Character Review
        if not problem_rows.empty:
            st.subheader(f"File: {file.name}")
            decision = review_special_char_rows(problem_rows, file_key) 
            
            # If we reach here, a decision has been made (or st.stop() was called)

            if decision == "delete":
                # Only delete from the working dataframe copy
                df.drop(problem_rows.index, inplace=True)
                deleted_rows_count = len(problem_rows)

            elif decision == "cancel":
                # Save the cancellation result and return
                st.session_state[result_key] = f"🟡 Canceled processing for {file.name}."
                return st.session_state[result_key]

        # 3. Main Cleaning Logic (Only runs after decision or if no special chars)
        
        tower_col = next((c for c in df.columns if 'tower' in c.lower()), None)
        unit_col = next((c for c in df.columns if 'unit' in c.lower()), None)
        corp_col = next((c for c in df.columns if 'corporate' in c.lower()), None)

        if not unit_col:
            st.session_state[result_key] = f"⚠️ No 'Unit' column found in {file.name}."
            return st.session_state[result_key]

        df['_CleanUnit'] = df[unit_col].apply(lambda x: x.strip())
        duplicate_units = df[df.duplicated('_CleanUnit', keep=False)]

        def build_unit(row):
            unit = row['_CleanUnit']
            tower = clean_tower(row[tower_col]) if tower_col else ''
            corp = row[corp_col].strip() if corp_col and pd.notna(row[corp_col]) else ''

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

        df_unique = df.drop_duplicates(subset=['Unit']).reset_index(drop=True)
        df_unique = df_unique.drop_duplicates()
        df_unique.drop(columns=['_CleanUnit'], inplace=True)
        df_unique.replace({'N/A': '', 'n/a': '', 'na': '', '': ''}, inplace=True)

        # 4. Output and Final Message
        
        # Save the output data in session state for the download button
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

        # Save the final result message and return
        st.session_state[result_key] = result_message
        return st.session_state[result_key]

    except Exception as e:
        # Save the error result and return
        st.session_state[result_key] = f"❌ Error processing {file.name}: {e}"
        return st.session_state[result_key]


# -------------------------------------------------
# STREAMLIT UI (Modified for Session State Initialization)
# -------------------------------------------------

# Initialize session state for the list of uploaded files when the script starts
if 'uploaded_files_keys' not in st.session_state:
    st.session_state['uploaded_files_keys'] = []

st.title("🏢 Unit Configuration Cleaner Tool")

def handle_upload():
    # Clear processing data if new files are uploaded
    keys_to_delete = []
    for key in st.session_state['uploaded_files_keys']:
        keys_to_delete.extend([f'result_{key}', f'data_{key}', f'decision_{key}', f'choice_{key}', f'output_{key}'])

    for key in keys_to_delete:
        if key in st.session_state:
            del st.session_state[key]
    
    # Map the new files to unique keys for session state management
    # Note: st.session_state.uploaded_files_widget holds the new list of files
    if st.session_state.uploaded_files_widget:
        st.session_state['uploaded_files_keys'] = [f"file_{i}" for i in range(len(st.session_state.uploaded_files_widget))]
    else:
         st.session_state['uploaded_files_keys'] = []

    
# Use a key to ensure the file_uploader persists its value across reruns
uploaded_files = st.file_uploader(
    "Select Excel or CSV Files",
    type=['xlsx', 'csv'],
    accept_multiple_files=True,
    key='uploaded_files_widget',
    on_change=handle_upload # Trigger function when files change
)

if uploaded_files:
    # Ensure the keys are set correctly based on the current upload list
    if len(st.session_state['uploaded_files_keys']) != len(uploaded_files):
        # This handles the initial load where on_change might not have been triggered yet
        st.session_state['uploaded_files_keys'] = [f"file_{i}" for i in range(len(uploaded_files))]

    st.info("Scroll down as each file will be processed one-by-one. Processing for each file will only proceed once any special character decisions are confirmed.")
    
    results = []
    has_pending_review = False # Flag to detect if we stopped processing

    # Loop through the files using their corresponding session state keys
    for i, file_key in enumerate(st.session_state['uploaded_files_keys']):
        file = uploaded_files[i] # Get the file object
        
        # Only display file processing information if the result isn't already saved (i.e., not fully processed)
        # and we haven't hit a pending review yet.
        is_processed = f"result_{file_key}" in st.session_state
        
        if not is_processed and not has_pending_review:
            st.divider()
            st.header(f"📄 Processing File {i+1}: **{file.name}**")
        
        # The function will now handle saving the result to session state and calling st.stop() if review is needed
        try:
            result = clean_units_streamlit(file, file_key)
            results.append(result)
        except st.ScriptRunner.StopException:
             # This exception is raised when st.stop() is called inside clean_units_streamlit/review_special_char_rows
            has_pending_review = True
            break # Break the loop to ensure no further files are processed until the rerun

    # After the loop, display the results summary
    st.divider()
    st.subheader("📌 Results Summary")
    
    # Display results for all files that have been processed or had their result stored
    for i, file_key in enumerate(st.session_state['uploaded_files_keys']):
        if f"result_{file_key}" in st.session_state:
             st.write(st.session_state[f"result_{file_key}"])
        # If the loop was stopped due to a pending review, the last file's decision is displayed above the divider
