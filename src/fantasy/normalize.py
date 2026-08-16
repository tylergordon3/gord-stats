"""
Small, dependency-light helpers for cleaning IDs and names so values from
different sources compare equal.
"""
import re
import unicodedata

import pandas as pd

# Name suffixes stripped before matching (already lowercased, punctuation gone).
_SUFFIX_RE = re.compile(r"\s+(jr|sr|ii|iii|iv|v)\.?$")


def clean_id(value):
    """Coerce any source's ID into a stable string, or None.

    Handles the common cases: ints stored as floats ("12345.0" -> "12345"),
    pandas/NumPy NaN, and literal "nan"/"none" strings.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none", "<na>"}:
        return None
    # Trailing ".0" from float-typed integer IDs read out of pandas.
    if re.fullmatch(r"-?\d+\.0", text):
        text = text[:-2]
    return text


def clean_id_series(series: pd.Series) -> pd.Series:
    """Vectorized clean_id for a whole column."""
    return series.map(clean_id).astype("object")


def normalize_name(name):
    """Reduce a display name to a match key.

    "Amon-Ra St. Brown" -> "amonrastbrown", "Michael Badgley Jr." -> "michaelbadgley".
    """
    if not isinstance(name, str) or name.strip() == "":
        return None
    # Fold accents: "Estimé" -> "Estime", "Añez" -> "Anez".
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[.'`]", "", text)        # drop periods / apostrophes
    text = _SUFFIX_RE.sub("", text)          # drop generational suffix
    text = re.sub(r"[^a-z0-9]", "", text)    # drop spaces, hyphens, anything left
    return text or None
