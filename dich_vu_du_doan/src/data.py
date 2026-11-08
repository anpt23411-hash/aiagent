"""Deterministic cleaning only; learned transformations belong in CV pipelines."""
import hashlib
import json
from pathlib import Path

import pandas as pd

SEED = 42
ALIASES = {
    "PreferredLoginDevice": {"Phone": "Mobile Phone"},
    "PreferredPaymentMode": {"CC": "Credit Card", "COD": "Cash on Delivery"},
    "PreferedOrderCat": {"Mobile": "Mobile Phone"},
}


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str, allow_nan=False), encoding="utf-8")


def load_clean(path, sheet):
    if not Path(path).is_file():
        raise FileNotFoundError(f"Missing real dataset: {path}")
    book = pd.ExcelFile(path)
    if sheet not in book.sheet_names:
        raise ValueError(f"Requested sheet {sheet!r}; available: {book.sheet_names!r}")
    raw = pd.read_excel(book, sheet_name=sheet)
    return clean(raw)


def clean(raw):
    d = raw.copy()
    d.columns = d.columns.str.strip()
    if d.columns.duplicated().any() or not {"CustomerID", "Churn", "Tenure"}.issubset(d):
        raise ValueError("Missing required columns or duplicate column names")
    before = len(d)
    raw_dupes = int(d.drop(columns="CustomerID").duplicated().sum())
    for c in d.select_dtypes(include=["object", "string"]).columns:
        d[c] = d[c].astype("string").str.strip().replace("", pd.NA)
    y = pd.to_numeric(d.Churn, errors="raise")
    if y.isna().any() or not set(y.unique()).issubset({0, 1}) or y.nunique() != 2:
        raise ValueError("Churn must contain both 0 and 1 and no missing/unknown labels")
    d["Churn"] = y.astype(int)
    for c, mapping in ALIASES.items():
        if c in d:
            d[c] = d[c].replace(mapping)
    features = d.drop(columns=["CustomerID", "Churn"])
    conflicts = d.groupby(list(features.columns), dropna=False).Churn.nunique().gt(1).sum()
    if conflicts:
        raise ValueError(f"{conflicts} identical feature groups have conflicting labels; adjudicate first")
    duplicate = d.drop(columns="CustomerID").duplicated()
    d = d.loc[~duplicate].copy()
    audit = {"rows_before": before, "duplicates_before_normalization_excluding_id": raw_dupes,
             "duplicates_after_normalization_excluding_id": int(duplicate.sum()), "rows_after": len(d),
             "class_counts_before": raw.Churn.value_counts().to_dict(),
             "class_counts_after": d.Churn.value_counts().to_dict(),
             "missing_after": d.isna().sum().to_dict(), "alias_rules": ALIASES,
             "outliers_removed": 0, "conflicting_feature_groups": int(conflicts)}
    return d, audit


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
