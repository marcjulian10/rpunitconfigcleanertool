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
        return pd.read_csv(file, dtype=str, keep_default_na=False)
    else:
        raise ValueError(f"Unsupported file format for {filename}. Please use .csv or .xlsx")


def clean_tower(tower_value):
    if not tower_value or str(tower_value).strip().lower() in ['n/a', 'na', '', 'N/A']:
        return ''
    return str(tower_value).strip()


# -------------------------------------------------
# STREAMLIT SPECIAL CHARACTER REVIEW HANDLER
# -------------------------------------------------

def review_special_char_rows(df, key_prefix):
    """
    Since Streamlit cannot open dialogs, this section appears on the webpage
    whenever special-character rows exist.
    """
    st.warning("⚠️ Special characters detected in this file!")
    st.write("Choose whether to keep or delete the rows before continuing.")

    st.dataframe(df)

    choice = st.radio(
        "Select an action:",
        ("Keep These Rows", "Delete These Rows", "Cancel Processing"),
        key=f"radio_{key_prefix}"
    )

    if st.button("Confirm", key=f"confirm_{key_prefix}"):
        if choice == "Keep These Rows":
            return "keep"
        elif choice == "Delete These Rows":
            return "delete"
        else:
            return "cancel"

    return None  # No decision yet


# -------------------------------------------------
# Main Cleaning Logic (modified only for Streamlit I/O)
# -------------------------------------------------

def clean_units_streamlit(file, file_key):
    try:
        df = read_file(file)

        special_char_mask = df.apply(
            lambda row: row.astype(str).apply(contains_special_chars).any(),
            axis=1
        )

        problem_rows = df[special_char_mask]
        deleted_rows_count = 0

        if not problem_rows.empty:
            st.subheader(f"File: {file.name}")
            decision = review_special_char_rows(problem_rows, file_key)

            if decision is None:
                st.stop()  # Wait for user decision

            if decision == "delete":
                df.drop(problem_rows.index, inplace=True)
                deleted_rows_count = len(problem_rows)

            elif decision == "cancel":
                return f"🟡 Canceled processing for {file.name}."

        tower_col = next((c for c in df.columns if 'tower' in c.lower()), None)
        unit_col = next((c for c in df.columns if 'unit' in c.lower()), None)
        corp_col = next((c for c in df.columns if 'corporate' in c.lower()), None)

        if not unit_col:
            return f"⚠️ No 'Unit' column found in {file.name}."

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

        # Output file as downloadable CSV
        output = df_unique.to_csv(index=False).encode('utf-8')

        st.download_button(
            label=f"⬇️ Download Cleaned File ({file.name})",
            data=output,
            file_name=file.name.replace('.xlsx', '_cleaned.csv').replace('.csv', '_cleaned.csv'),
            mime='text/csv'
        )

        result_message = f"✅ Processed: {file.name}\n"
        if deleted_rows_count > 0:
            result_message += f"🗑️ Deleted {deleted_rows_count} rows with special characters.\n"
        result_message += f"🔢 Total Unique Units: {len(df_unique)}"

        return result_message

    except Exception as e:
        return f"❌ Error processing {file.name}: {e}"


# -------------------------------------------------
# STREAMLIT UI
# -------------------------------------------------

st.title("🏢 Unit Configuration Cleaner Tool")

uploaded_files = st.file_uploader(
    "Select Excel or CSV Files",
    type=['xlsx', 'csv'],
    accept_multiple_files=True
)

if uploaded_files:
    st.info("Scroll down as each file will be processed one-by-one.")
    results = []

    for i, file in enumerate(uploaded_files):
        st.divider()
        st.header(f"📄 Processing File {i+1}: {file.name}")
        result = clean_units_streamlit(file, f"file_{i}")
        results.append(result)

    st.divider()
    st.subheader("📌 Results Summary")
    for res in results:
        st.write(res)
