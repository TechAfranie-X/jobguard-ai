"""Simple, reusable data-preparation functions for JobGuard AI.

Used by notebooks/02_data_preprocessing.ipynb (and later by the model
notebooks and the Streamlit app, so every part of the project prepares
text in exactly the same way).
"""

import pandas as pd

# The five text columns that are combined into one text field.
TEXT_COLUMNS = ["title", "company_profile", "description", "requirements", "benefits"]


def load_data(path):
    """Read the raw EMSCAD CSV file into a DataFrame."""
    return pd.read_csv(path)


def remove_duplicates(df):
    """First pass: drop postings that are identical in every column except job_id.

    job_id is ignored because every row has a different job_id even when the
    posting itself is a copy. This is NOT enough for an NLP project: two
    postings can have identical text but a different location, so they
    survive this step. remove_duplicate_text (below) handles that case.
    """
    columns_to_compare = [column for column in df.columns if column != "job_id"]
    df_no_duplicates = df.drop_duplicates(subset=columns_to_compare, keep="first")
    return df_no_duplicates.reset_index(drop=True)


def prepare_text_columns(df):
    """Replace missing values in the text columns with empty strings."""
    df = df.copy()
    df[TEXT_COLUMNS] = df[TEXT_COLUMNS].fillna("")
    return df


def create_combined_text(df):
    """Join the text columns into one string, with a label before each part.

    Expects the text columns to have no missing values
    (run prepare_text_columns first).
    """
    return (
        "TITLE: " + df["title"] + "\n"
        + "COMPANY PROFILE: " + df["company_profile"] + "\n"
        + "DESCRIPTION: " + df["description"] + "\n"
        + "REQUIREMENTS: " + df["requirements"] + "\n"
        + "BENEFITS: " + df["benefits"]
    )


def count_conflicting_text(df):
    """Count groups of identical combined_text that have different labels.

    A conflict would mean the same text is labelled both legitimate and
    fraudulent, which needs a human decision.
    """
    labels_per_text = df.groupby("combined_text")["fraudulent"].nunique()
    return int((labels_per_text > 1).sum())


def remove_duplicate_text(df):
    """Keep only the first posting for each unique combined_text.

    Stops with an error if identical text has conflicting labels, so rows
    are never removed silently in that case.
    """
    conflicts = count_conflicting_text(df)
    if conflicts > 0:
        raise ValueError(f"{conflicts} text group(s) have conflicting labels - review before removing.")
    df_unique_text = df.drop_duplicates(subset="combined_text", keep="first")
    return df_unique_text.reset_index(drop=True)
