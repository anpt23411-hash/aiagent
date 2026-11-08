"""Fold-local preprocessing for the detailed thesis methodology (§3.5–3.7)."""
import warnings
import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, fisher_exact
from statsmodels.stats.multitest import multipletests
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from imblearn.over_sampling import SMOTENC
from imblearn.pipeline import Pipeline
from .data import ALIASES

NOMINAL = ["Gender", "MaritalStatus", "PreferredLoginDevice", "PreferredPaymentMode", "PreferedOrderCat"]
SENSITIVE = ["Complain", "DaySinceLastOrder", "OrderCount", "CouponUsed", "CashbackAmount"]


def ratios(X):
    out = X.copy()
    denominator = out.OrderCount.where(out.OrderCount > 0)
    out["CashbackPerOrder"] = out.CashbackAmount / denominator
    out["CouponRate"] = out.CouponUsed / denominator
    return out


def missing_association(X, y):
    rows = []
    for c in X:
        missing = X[c].isna()
        if not missing.any() or missing.all():
            continue
        tab = pd.crosstab(missing, np.asarray(y)).reindex(index=[False, True], columns=[0, 1], fill_value=0)
        _, p, _, expected = chi2_contingency(tab, correction=False)
        method = "chi_square"
        if (expected < 5).any():
            _, p = fisher_exact(tab)
            method = "fisher_exact"
        rows.append(dict(feature=c, missing=int(missing.sum()), missing_fraction=float(missing.mean()),
                         positive_rate_missing=float(np.asarray(y)[missing].mean()),
                         positive_rate_observed=float(np.asarray(y)[~missing].mean()), p=float(p), test=method))
    t = pd.DataFrame(rows)
    if len(t):
        t["q_fdr_bh"] = multipletests(t.p, method="fdr_bh")[1]
    return t


class PrepareFrame(TransformerMixin, BaseEstimator):
    def __init__(self, flags="significant", include_new=True, ratio=None, tenure_threshold=1):
        self.flags = flags
        self.include_new = include_new
        self.ratio = ratio
        self.tenure_threshold = tenure_threshold

    def fit(self, X, y=None):
        if {"CustomerID", "Churn"} & set(X):
            raise ValueError("ID/target forbidden in model input")
        if X.columns.duplicated().any():
            raise ValueError("Duplicate input columns")
        X = X.copy()
        for c, mapping in ALIASES.items():
            if c in X:
                X[c] = self._strings(X[c]).replace(mapping)
        self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        self.nominal_ = [c for c in NOMINAL if c in X]
        self.numeric_ = [c for c in X if c not in self.nominal_]
        self.associations_ = missing_association(X, y) if y is not None else pd.DataFrame()
        self.flag_columns_ = (self.associations_.loc[self.associations_.q_fdr_bh < .05, "feature"].tolist()
                              if self.flags == "significant" and len(self.associations_) else [])
        if self.flags == "all":
            self.flag_columns_ = [c for c in X if X[c].isna().any()]
        self.categories_ = {}
        for c in self.nominal_:
            v = self._strings(X[c])
            mode = v.mode().iloc[0] if len(v.mode()) else "<MISSING>"
            self.categories_[c] = [mode] + sorted(set(v.dropna()) - {mode})
        values = ratios(X) if self.ratio else X
        self.ratio_columns_ = ([self.ratio] if isinstance(self.ratio, str) else list(self.ratio or []))
        self.value_columns_ = self.numeric_ + self.ratio_columns_
        self.medians_ = {c: float(values[c].median()) if values[c].notna().any() else 0. for c in self.value_columns_}
        self.log_columns_ = [c for c in self.value_columns_ if c != "Complain" and values[c].min() >= 0 and values[c].skew() > 1]
        return self

    @staticmethod
    def _strings(s):
        return s.astype("string").str.strip().replace("", pd.NA)

    def transform(self, X):
        if set(X) != set(self.feature_names_in_):
            raise ValueError("Input schema mismatch (missing/extra/ID/target columns)")
        X = X.loc[:, self.feature_names_in_].copy()
        for c, mapping in ALIASES.items():
            if c in X:
                X[c] = self._strings(X[c]).replace(mapping)
        if self.ratio:
            X = ratios(X)
        out = pd.DataFrame(index=X.index)
        for c in self.value_columns_:
            v = pd.to_numeric(X[c], errors="raise").astype(float)
            if not np.isfinite(v.dropna()).all() or (v.dropna() < 0).any():
                raise ValueError(f"Nonfinite/negative value in {c}; review input")
            out[c] = v.fillna(self.medians_[c])
            if c in self.log_columns_:
                out[c] = np.log1p(out[c])
        for c, levels in self.categories_.items():
            mapping = {v: i for i, v in enumerate(levels)}
            out[c] = self._strings(X[c]).fillna(levels[0]).map(mapping).fillna(-1).astype(float)
        for c in self.flag_columns_:
            out[c + "Missing"] = X[c].isna().astype(float)
        if self.include_new:
            out["__TenureMissing"] = X.Tenure.isna().astype(float)
            out["IsNewCustomer"] = (X.Tenure.le(self.tenure_threshold) & X.Tenure.notna()).astype(float)
        out.attrs = {"log_columns": self.log_columns_, "categories": self.categories_}
        return out


class LogicalSMOTENC(BaseEstimator):
    """Scale distances only, preserve flags, and rebuild dependent features after sampling."""
    def __init__(self, sampling_strategy=1., k_neighbors=3, tenure_threshold=1, random_state=42):
        self.sampling_strategy = sampling_strategy
        self.k_neighbors = k_neighbors
        self.tenure_threshold = tenure_threshold
        self.random_state = random_state

    def fit_resample(self, X, y):
        attrs = X.attrs.copy()
        counts = pd.Series(np.asarray(y)).value_counts()
        if counts.min()/counts.max() >= self.sampling_strategy:
            self.sampled_class_counts_ = {int(k): int(v) for k, v in counts.items()}
            self.sampling_skipped_ = "Requested minority ratio already reached; oversampling does not remove observations"
            return X.copy(), y.copy()
        discrete = [c for c in X if c in NOMINAL or c == "Complain" or c.endswith("Missing") or c == "IsNewCustomer"]
        continuous = [c for c in X if c not in discrete]
        scaler = StandardScaler()
        z = X.copy()
        z[continuous] = scaler.fit_transform(z[continuous])
        self.sampler_ = SMOTENC(categorical_features=discrete, sampling_strategy=self.sampling_strategy,
                               k_neighbors=self.k_neighbors, random_state=self.random_state)
        z, labels = self.sampler_.fit_resample(z, y)
        z[continuous] = scaler.inverse_transform(z[continuous])
        if "IsNewCustomer" in z:
            tenure = np.expm1(z.Tenure) if "Tenure" in attrs["log_columns"] else z.Tenure
            z["IsNewCustomer"] = ((tenure <= self.tenure_threshold) & z["__TenureMissing"].eq(0)).astype(float)
        for ratio, numerator in [("CashbackPerOrder", "CashbackAmount"), ("CouponRate", "CouponUsed")]:
            if ratio in z:
                def raw(c):
                    return np.expm1(z[c]) if c in attrs["log_columns"] else z[c]
                v = raw(numerator) / raw("OrderCount").where(raw("OrderCount") > 0)
                z[ratio] = np.log1p(v) if ratio in attrs["log_columns"] else v
                z[ratio] = z[ratio].fillna(X[ratio].median())
        z.attrs = attrs
        self.sampled_class_counts_ = {int(k): int((np.asarray(labels) == k).sum()) for k in (0, 1)}
        return z, labels


class FinishFrame(TransformerMixin, BaseEstimator):
    def __init__(self, scale=False):
        self.scale = scale

    def fit(self, X, y=None):
        self.nominal_ = [c for c in NOMINAL if c in X]
        self.numeric_ = [c for c in X if c not in self.nominal_ and not c.startswith("__")]
        self.scaled_ = [c for c in self.numeric_ if not c.endswith("Missing") and c not in {"Complain", "IsNewCustomer"}]
        self.reference_categories_ = X.attrs.get("categories", {})
        self.encoder_ = OneHotEncoder(drop=[0.] * len(self.nominal_), handle_unknown="ignore", sparse_output=False)
        self.encoder_.fit(X[self.nominal_])
        self.scaler_ = StandardScaler().fit(X[self.scaled_]) if self.scale else None
        self.feature_names_out_ = np.r_[self.numeric_, self.encoder_.get_feature_names_out(self.nominal_)]
        return self

    def transform(self, X):
        numeric = X[self.numeric_].copy()
        if self.scale:
            numeric[self.scaled_] = self.scaler_.transform(numeric[self.scaled_])
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Found unknown categories")
            encoded = self.encoder_.transform(X[self.nominal_])
        return np.column_stack([numeric.to_numpy(), encoded])

    def get_feature_names_out(self, input_features=None):
        return self.feature_names_out_


def build_thesis_pipeline(estimator, algorithm, scenario, features=None):
    features = features or {}
    steps = [("prepare", PrepareFrame(**features))]
    if scenario["sampling"] == "smotenc":
        steps.append(("sample", LogicalSMOTENC(sampling_strategy=scenario["ratio"],
                                              k_neighbors=scenario.get("k_neighbors", 3),
                                              tenure_threshold=features.get("tenure_threshold", 1))))
    steps.extend([("finish", FinishFrame(scale=algorithm == "logistic_regression")), ("model", estimator)])
    return Pipeline(steps)
