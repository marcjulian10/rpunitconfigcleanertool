import streamlit as st
import pandas as pd
import os
import re
from io import StringIO, BytesIO

# -------------------------------------------------
# Helpers
# -------------------------------------------------

def is_date_format(s):
"""
Checks if a string looks like a date (e.g., 2023-01-01, 12/12/2023, 10.10.20).
"""
s_str = str(s).strip()
# Regex checks for digits separated by -, /, or .
# Matches patterns like: 1-1-1, 2023-10-10, 10/10/2020, 2020.01.01
date_pattern = re.compile(r'\d{1,4}[-./]\d{1,2}[-./]\d{1,4}')
return bool(date_pattern.search(s_str))

def contains_issues(s):
"""
Checks for special characters OR date patterns.
Strict Mode: Only Alphanumeric and Spaces are allowed.
"""
if pd.isna(s):
return False

s_str = str(s).strip()

# Ignore "N/A" variants/empties
if s_str.upper() in ['N/A', 'NA', 'n/a', 'na', '']:
return False

# 1. Check for Date-like patterns explicitly
if is_date_format(s_str):
return True

# 2. Strict Special Character Check
# Flags ANYTHING that is not a Letter (a-z), Number (0-9), or Space.
# This intentionally flags Hyphens (-), Slashes (/), Dots (.), etc.
strict_pattern = re.compile(r'[^a-zA-Z0-9\s]')
return bool(strict_pattern.search(s_str))


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
# This ensures N/A is removed/turned into empty string
if not tower_value or str(tower_value).strip().lower() in ['n/a', 'na', '', 'N/A']:
return ''
return str(tower_value).strip()


# -------------------------------------------------
# INTERACTIVE REVIEW HANDLERS
# -------------------------------------------------

def review_issues(df, file_key):
"""
Handles user decision for invalid Unit rows (Special Chars or Dates).
"""
decision_key = f"issue_decision_{file_key}"

st.warning(f"⚠️ Issues detected in the 'Unit' column of {len(df)} rows!")
st.write("These rows contain **Special Characters (like hyphens)** or **Date Formats**.")
st.write("Please review and decide:")

st.dataframe(df)

if decision_key not in st.session_state:
st.session_state[decision_key] = None

def set_issue_choice():
st.session_state[f"issue_choice_val_{file_key}"] = st.session_state[f"issue_radio_{file_key}"]

st.radio(
"Select an action:",
("Keep These Rows", "Delete These Rows", "Cancel Processing"),
key=f"issue_radio_{file_key}",
on_change=set_issue_choice
)

current_choice = st.session_state.get(f"issue_choice_val_{file_key}", "Keep These Rows")

def set_decision():
st.session_state[decision_key] = {
"Keep These Rows": "keep",
"Delete These Rows": "delete",
"Cancel Processing": "cancel"
}.get(current_choice)
st.rerun()

if st.session_state[decision_key] is None:
st.button("Confirm Action", key=f"confirm_issue_{file_key}", on_click=set_decision)
st.stop()

return st.session_state[decision_key]


def review_duplicates(df, duplicates_df, file_key):
"""
Handles user decision for duplicate Unit rows.
"""
decision_key = f"dup_decision_{file_key}"

st.warning(f"⚠️ {len(duplicates_df)} Duplicate entries found (same Tower + Unit combination)!")
st.write("These rows result in identical Unit IDs.")

st.dataframe(duplicates_df.sort_values(by='Unit'))

if decision_key not in st.session_state:
st.session_state[decision_key] = None

def set_dup_choice():
st.session_state[f"dup_choice_val_{file_key}"] = st.session_state[f"dup_radio_{file_key}"]

st.radio(
"Select duplicate handling:",
("Keep All Copies", "Retain 1 Copy (Remove Duplicates)", "Cancel Processing"),
key=f"dup_radio_{file_key}",
on_change=set_dup_choice
)

current_choice = st.session_state.get(f"dup_choice_val_{file_key}", "Keep All Copies")

def set_decision():
st.session_state[decision_key] = {
"Keep All Copies": "keep_all",
"Retain 1 Copy (Remove Duplicates)": "retain_one",
"Cancel Processing": "cancel"
}.get(current_choice)
st.rerun()

if st.session_state[decision_key] is None:
st.button("Confirm Duplicate Action", key=f"confirm_dup_{file_key}", on_click=set_decision)
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

if not unit_col:
st.session_state[result_key] = f"⚠️ No 'Unit' column found in {file.name}."
return st.session_state[result_key]

# ---------------------------
# CHECK 1: Issues (Special Chars / Dates) in UNIT COLUMN ONLY
# ---------------------------

# We check specifically for date formats or disallowed characters
issue_mask = df[unit_col].astype(str).apply(contains_issues)
problem_rows = df[issue_mask]
deleted_rows_count = 0

if not problem_rows.empty:
st.subheader(f"File: {file.name}")
decision = review_issues(problem_rows, file_key)

if decision == "delete":
df.drop(problem_rows.index, inplace=True)
deleted_rows_count = len(problem_rows)
elif decision == "cancel":
st.session_state[result_key] = f"🟡 Canceled processing for {file.name} (Issues Detected)."
return st.session_state[result_key]

# ---------------------------
# CONSTRUCT UNIT STRING
# ---------------------------
df['_CleanUnit'] = df[unit_col].astype(str).apply(lambda x: x.strip())

def build_unit(row):
unit = row['_CleanUnit']
tower = clean_tower(row[tower_col]) if tower_col else ''

# Logic: If Tower exists, concatenate it.
if tower:
return f"{tower} - {unit}"
else:
return unit

df['Unit'] = df.apply(build_unit, axis=1)

# ---------------------------
# CHECK 2: Duplicates
# ---------------------------
duplicate_mask = df.duplicated(subset=['Unit'], keep=False)
duplicates_df = df[duplicate_mask]

if not duplicates_df.empty:
st.subheader(f"File: {file.name}")
dup_decision = review_duplicates(df, duplicates_df, file_key)

if dup_decision == "retain_one":
# Keep first occurrence, drop rest
df = df.drop_duplicates(subset=['Unit'], keep='first')
elif dup_decision == "cancel":
st.session_state[result_key] = f"🟡 Canceled processing for {file.name} (Duplicates)."
return st.session_state[result_key]

# ---------------------------
# FINAL CLEANUP & OUTPUT
# ---------------------------
df_final = df.reset_index(drop=True)
if '_CleanUnit' in df_final.columns:
df_final.drop(columns=['_CleanUnit'], inplace=True)

# Final cleanup for any remaining N/A strings
df_final.replace({'N/A': '', 'n/a': '', 'na': '', '': ''}, inplace=True)

output = df_final.to_csv(index=False).encode('utf-8')
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
result_message += f"🗑️ Deleted {deleted_rows_count} rows with issues (Dates/Special Chars).\n"
result_message += f"🔢 Final Row Count: {len(df_final)}"

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
# Clear all session state related to file processing
keys_to_delete = []
# Find all keys starting with our prefixes
prefixes = ['result_', 'data_', 'issue_decision_', 'issue_choice_val_', 'dup_decision_', 'dup_choice_val_', 'output_']

for key in st.session_state.keys():
for prefix in prefixes:
if key.startswith(prefix):
keys_to_delete.append(key)

for key in keys_to_delete:
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

st.info("Files are processed sequentially. You may be prompted to make decisions for Special Characters/Dates (Unit only) and Duplicates.")

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
