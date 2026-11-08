"""Lõi của dịch vụ dự đoán cho nguyên mẫu AI Agent (mục 3.10 của khóa luận).

Mọi giá trị định lượng (xác suất, điểm, nhóm, đóng góp SHAP, số lượng, danh sách) được tính ở đây
bằng pipeline đã lưu và các quy tắc trong metadata.json. Agent chỉ nhận kết quả, không tự tính.
Chỉ có thao tác đọc; không có hàm nào ghi hay sửa dữ liệu.
"""
import hashlib
import json
import math
import re
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
NOMINAL = ["Gender", "MaritalStatus", "PreferredLoginDevice", "PreferredPaymentMode", "PreferedOrderCat"]
ALIASES = {"PreferredLoginDevice": {"Phone": "Mobile Phone"},
           "PreferredPaymentMode": {"CC": "Credit Card", "COD": "Cash on Delivery"},
           "PreferedOrderCat": {"Mobile": "Mobile Phone"}}   # giống src/data.py
GROUP_VI = {"low": "thấp", "medium": "trung bình", "high": "cao"}
GROUP_ALIASES = {"low": "low", "thap": "low", "thấp": "low", "nguy co thap": "low",
                 "medium": "medium", "trung binh": "medium", "trung bình": "medium", "trung_binh": "medium",
                 "high": "high", "cao": "high", "nguy co cao": "high"}
EQUALITY_FILTERS = {"CityTier": [1, 2, 3], "Complain": [0, 1], "SatisfactionScore": [1, 2, 3, 4, 5]}
RANGE_FILTERS = ["Tenure", "WarehouseToHome", "HourSpendOnApp", "NumberOfDeviceRegistered", "NumberOfAddress",
                 "OrderAmountHikeFromlastYear", "CouponUsed", "OrderCount", "DaySinceLastOrder", "CashbackAmount"]
MAX_LIST = 50
MAX_TOP_K = 5
DERIVED_LABELS = {"IsNewCustomer": "IsNewCustomer (khách mới: Tenure ≤ 1)"}
DATA_SCOPE = "CRM thử nghiệm: 1.015 hồ sơ của tập holdout, không chứa nhãn Churn"
MEANING = ("Xác suất là nguy cơ hồ sơ thuộc nhóm mang nhãn Churn = 1 theo dữ liệu nghiên cứu, "
           "không phải dự báo chắc chắn rằng khách hàng sẽ rời bỏ.")


class ServiceError(Exception):
    """Lỗi kỹ thuật của dịch vụ (trả về HTTP 500)."""


def vi_num(x, nd=4):
    """Định dạng số kiểu Việt Nam: dấu phẩy thập phân."""
    return f"{x:.{nd}f}".replace(".", ",")


def vi_pct(x, nd=1):
    return f"{100 * x:.{nd}f}".replace(".", ",") + "%"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _clean_value(v):
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return int(f) if f.is_integer() else f
    return str(v)


class ChurnService:
    def __init__(self, root=ROOT):
        root = Path(root)
        self.manifest = json.loads((root / "model/manifest.json").read_text(encoding="utf-8"))
        m = self.manifest["model"]
        # Kiểm tra mã băm TRƯỚC khi tải (joblib có thể thực thi mã khi tải).
        for rel, expected in [(m["file"], m["sha256"]), ("model/metadata.json", m["metadata_sha256"]),
                              (self.manifest["crm"]["file"], self.manifest["crm"]["sha256"])]:
            if sha256(root / rel) != expected:
                raise ServiceError(f"Mã băm của {rel} không khớp manifest; từ chối tải.")
        self.metadata = json.loads((root / "model/metadata.json").read_text(encoding="utf-8"))
        import sys
        sys.path.insert(0, str(root))          # lớp PrepareFrame/FinishFrame nằm trong src.thesis_preprocessing
        self.pipeline = joblib.load(root / m["file"])
        self.prepare = self.pipeline.named_steps["prepare"]
        self.finish = self.pipeline.named_steps["finish"]
        self.estimator = self.pipeline.named_steps["model"]
        if list(self.estimator.classes_) != [0, 1]:
            raise ServiceError("Thứ tự lớp của mô hình không phải [0, 1].")
        self.columns = self.metadata["input_columns"]
        self.threshold = float(self.metadata["threshold"])
        self.groups = {k: tuple(v) for k, v in self.metadata["risk_groups"].items()}
        self.model_version = f"{m['algorithm']}/{m['scenario']}/{m['version']} sha256:{m['sha256'][:12]}"
        self.service_version = self.manifest["service_version"]
        crm = pd.read_csv(root / self.manifest["crm"]["file"])
        if "Churn" in crm.columns:
            raise ServiceError("CRM thử nghiệm không được chứa nhãn Churn.")
        crm["CustomerID"] = crm["CustomerID"].astype(int)
        self.crm = crm.set_index("CustomerID", drop=False)
        dd = pd.read_csv(root / "data/tu_dien_du_lieu.csv")
        self.descriptions = {r.variable: r.description for r in dd.itertuples() if r.variable in self.columns}
        self.categories = self.prepare.categories_
        self.feature_names = list(self.finish.get_feature_names_out())
        self.feature_groups = {}
        for i, name in enumerate(self.feature_names):
            original = next((c for c in NOMINAL if name.startswith(c + "_")), name)
            self.feature_groups.setdefault(original, []).append(i)
        import shap
        self.shap_version = shap.__version__
        # Đúng cấu hình mục 3.9.3: TreeExplainer tree_path_dependent trên điểm thô (log-odds) của HGB.
        self.explainer = shap.TreeExplainer(self.estimator, feature_perturbation="tree_path_dependent", model_output="raw")
        # Chấm điểm toàn bộ CRM một lần khi khởi động, bằng chính hàm dự đoán của từng hồ sơ.
        self.table = self._score_frame(self.crm[self.columns])
        self.table.index = self.crm.index

    # ---------- dự đoán (giống src/predict.py: predict_frame) ----------
    def _frame(self, X):
        if X.columns.duplicated().any() or set(X) != set(self.columns):
            raise ValueError(f"Cần đúng {len(self.columns)} thuộc tính đầu vào; không có CustomerID, Churn hay cột thừa.")
        X = X.loc[:, self.columns].copy()
        for column, dtype in self.metadata["input_dtypes"].items():
            if dtype.startswith(("float", "int")):
                X[column] = pd.to_numeric(X[column], errors="raise")
        return X

    def _score_frame(self, X):
        X = self._frame(X)
        p = self.estimator_proba(X)
        if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
            raise ServiceError("Xác suất không hợp lệ.")
        score = np.minimum(10, 1 + np.floor(10 * p)).astype(int)       # công thức (3.20)
        group = np.full(len(X), "", dtype=object)
        for name, (lo, hi) in self.groups.items():
            group[(score >= lo) & (score <= hi)] = name
        return pd.DataFrame({"probability": p, "score": score, "risk_group": group,
                             "above_threshold": p >= self.threshold}, index=X.index)

    def estimator_proba(self, X):
        return self.pipeline.predict_proba(X)[:, 1]

    # ---------- tiện ích ----------
    @staticmethod
    def parse_id(value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return None, "invalid_id", "Thiếu mã khách hàng."
        s = str(value).strip()
        if isinstance(value, float) and value.is_integer():
            s = str(int(value))
        if not re.fullmatch(r"\d{1,9}", s):
            return None, "invalid_id", f"Mã khách hàng '{s[:20]}' không hợp lệ: CustomerID là một số nguyên dương."
        return int(s), None, None

    def _lookup(self, customer_id):
        cid, status, msg = self.parse_id(customer_id)
        if status:
            return None, {"status": status, "message": msg}
        if cid not in self.crm.index:
            return None, {"status": "not_found", "customer_id": cid,
                          "message": f"Không tìm thấy khách hàng có CustomerID = {cid} trong {DATA_SCOPE}."}
        return cid, None

    def _base(self):
        return {"model_version": self.model_version, "service_version": self.service_version, "data_scope": DATA_SCOPE}

    def _missing(self, row):
        return [c for c in self.columns if _clean_value(row[c]) is None]

    def _unknown_categories(self, row):
        out = []
        for c in NOMINAL:
            v = _clean_value(row[c])
            if v is None:
                continue
            v = ALIASES.get(c, {}).get(v.strip(), v.strip())
            if v not in self.categories[c]:
                out.append({"field": c, "value": v})
        return out

    @staticmethod
    def _group_code(value):
        if value is None or str(value).strip() == "":
            return None
        key = str(value).strip().lower().replace("_", " ")
        key = re.sub(r"^(nhóm|nhom)\s+", "", key)
        key = re.sub(r"^nguy cơ\s+", "nguy co ", key)
        if key in GROUP_ALIASES:
            return GROUP_ALIASES[key]
        key2 = key.replace("nguy co ", "")
        return GROUP_ALIASES.get(key2, "invalid")

    def _apply_filters(self, filters):
        if filters is None or filters == "" or filters == {}:
            return self.crm, {}, None
        if isinstance(filters, str):
            try:
                filters = json.loads(filters)
            except json.JSONDecodeError:
                return None, None, "filters phải là đối tượng JSON, ví dụ {\"CityTier\": 3}."
        if not isinstance(filters, dict):
            return None, None, "filters phải là đối tượng JSON."
        frame, applied = self.crm, {}
        allowed = sorted(list(EQUALITY_FILTERS) + NOMINAL + RANGE_FILTERS)
        for key, val in filters.items():
            field = next((c for c in allowed if c.lower() == str(key).strip().lower()), None)
            if field is None:
                return None, None, f"Không hỗ trợ lọc theo '{key}'. Các trường được phép: {', '.join(allowed)}."
            if field in RANGE_FILTERS:
                if isinstance(val, dict):
                    lo, hi = val.get("min"), val.get("max")
                else:
                    lo = hi = val
                try:
                    lo = None if lo is None else float(lo)
                    hi = None if hi is None else float(hi)
                except (TypeError, ValueError):
                    return None, None, f"Giá trị lọc của {field} phải là số hoặc {{\"min\": a, \"max\": b}}."
                col = pd.to_numeric(frame[field])
                mask = col.notna()
                if lo is not None:
                    mask &= col >= lo
                if hi is not None:
                    mask &= col <= hi
                frame = frame[mask]
                applied[field] = {k: v for k, v in (("min", lo), ("max", hi)) if v is not None}
                continue
            values = val if isinstance(val, list) else [val]
            if field in EQUALITY_FILTERS:
                try:
                    values = [int(float(v)) for v in values]
                except (TypeError, ValueError):
                    return None, None, f"Giá trị của {field} phải thuộc {EQUALITY_FILTERS[field]}."
                bad = [v for v in values if v not in EQUALITY_FILTERS[field]]
                if bad:
                    return None, None, f"Giá trị của {field} phải thuộc {EQUALITY_FILTERS[field]}."
                frame = frame[frame[field].isin(values)]
            else:
                levels = self.categories[field]
                norm = []
                for v in values:
                    v = ALIASES.get(field, {}).get(str(v).strip(), str(v).strip())
                    match = next((x for x in levels if x.lower() == v.lower()), None)
                    if match is None:
                        return None, None, f"Giá trị '{v}' của {field} không có trong dữ liệu. Giá trị hợp lệ: {', '.join(levels)}."
                    norm.append(match)
                values = norm
                frame = frame[frame[field].astype(str).isin(values)]
            applied[field] = values if len(values) > 1 else values[0]
        return frame, applied, None

    def _prediction_block(self, cid):
        r = self.table.loc[cid]
        p = float(r.probability)
        lo, hi = self.groups[r.risk_group]
        return {"probability": round(p, 6), "probability_display": vi_num(p, 4), "probability_percent_display": vi_pct(p, 1),
                "score": int(r.score), "risk_group": GROUP_VI[r.risk_group], "risk_group_code": r.risk_group,
                "risk_group_score_range": f"{lo}–{hi}", "threshold": round(self.threshold, 6), "threshold_display": vi_num(self.threshold, 4),
                "above_threshold": bool(r.above_threshold),
                "threshold_position": "bằng hoặc trên ngưỡng t*" if r.above_threshold else "dưới ngưỡng t*",
                "prediction_label_at_threshold": int(r.above_threshold)}

    # ---------- năm công cụ ----------
    def get_customer(self, customer_id=None, **_):
        cid, err = self._lookup(customer_id)
        if err:
            return err
        row = self.crm.loc[cid]
        profile = {c: _clean_value(row[c]) for c in self.columns}
        return {"status": "ok", "customer_id": cid, "profile": profile, "missing_fields": self._missing(row),
                "field_descriptions": self.descriptions, **self._base()}

    def predict_risk(self, customer_id=None, **_):
        cid, err = self._lookup(customer_id)
        if err:
            return err
        row = self.crm.loc[cid]
        # Dự đoán lại riêng hồ sơ này bằng cùng hàm, và đối chiếu với bảng điểm lúc khởi động.
        single = self._score_frame(self.crm.loc[[cid], self.columns])
        if abs(float(single.probability.iloc[0]) - float(self.table.loc[cid, "probability"])) > 1e-12:
            raise ServiceError("Dự đoán đơn lẻ không khớp bảng điểm.")
        missing, unknown = self._missing(row), self._unknown_categories(row)
        notes = []
        if missing:
            notes.append("Các trường bị thiếu đã được điền bằng trung vị của tập huấn luyện như khi huấn luyện; trạng thái thiếu cũng được mô hình sử dụng.")
        if unknown:
            notes.append("Có danh mục không xuất hiện trong dữ liệu huấn luyện; mô hình xử lý như nhóm tham chiếu nên độ tin cậy thấp hơn.")
        return {"status": "ok", "customer_id": cid, **self._prediction_block(cid), "missing_fields": missing,
                "unknown_categories": unknown, "data_notes": notes, "meaning": MEANING, **self._base()}

    def explain_customer(self, customer_id=None, top_k=3, **_):
        cid, err = self._lookup(customer_id)
        if err:
            return err
        try:
            k = int(float(top_k)) if top_k not in (None, "") else 3
        except (TypeError, ValueError):
            return {"status": "invalid_input", "message": "top_k phải là số nguyên từ 1 đến 5."}
        k = max(1, min(MAX_TOP_K, k))
        X = self._frame(self.crm.loc[[cid], self.columns])
        z = self.finish.transform(self.prepare.transform(X))
        values = np.asarray(self.explainer.shap_values(z, check_additivity=True))
        if values.ndim == 3:
            values = values[:, :, 1]
        base = float(np.asarray(self.explainer.expected_value).ravel()[0])
        output = float(self.estimator.decision_function(z)[0])
        err_add = abs(float(values[0].sum()) + base - output)
        if err_add > 1e-4:
            return {"status": "explain_error", "message": "Kiểm tra tính chất cộng của SHAP không đạt; không trả về giải thích.", **self._base()}
        row = self.crm.loc[cid]
        contrib = []
        for name, idx in self.feature_groups.items():
            v = float(values[0, idx].sum())
            if name in self.columns:
                raw = _clean_value(row[name])
                shown = "thiếu (đã điền trung vị)" if raw is None else raw
                label = name
            elif name.endswith("Missing"):
                base_col = name[:-len("Missing")]
                raw = 1 if _clean_value(row[base_col]) is None else 0
                shown = f"{raw} ({'thiếu' if raw else 'không thiếu'} {base_col})"
                label = f"{name} (cờ thiếu của {base_col})"
            else:
                raw = int(z[0, self.feature_names.index(name)])
                shown = raw
                label = DERIVED_LABELS.get(name, name)
            contrib.append({"feature": name, "label": label, "value": shown, "shap": round(v, 6),
                            "shap_display": ("+" if v >= 0 else "-") + vi_num(abs(v), 3)})
        inc = sorted([c for c in contrib if c["shap"] > 0], key=lambda c: -c["shap"])[:k]
        dec = sorted([c for c in contrib if c["shap"] < 0], key=lambda c: c["shap"])[:k]
        pred = self._prediction_block(cid)
        return {"status": "ok", "customer_id": cid, "method": "SHAP TreeExplainer (tree_path_dependent) trên điểm thô của HistGradientBoosting",
                "scale": "log-odds", "base_value": round(base, 6), "base_value_display": vi_num(base, 3),
                "output_log_odds": round(output, 6), "output_log_odds_display": vi_num(output, 3),
                "probability": pred["probability"], "probability_display": pred["probability_display"],
                "additivity_check": f"đạt (sai lệch {err_add:.1e})", "top_k": k,
                "increasing_factors": inc, "decreasing_factors": dec,
                "note": ("Đóng góp trên thang log-odds của mô hình: dấu + làm tăng, dấu − làm giảm điểm dự đoán. "
                         "Không quy đổi thành phần trăm xác suất và không phải nguyên nhân rời bỏ."), **self._base()}

    def count_by_group(self, risk_group=None, filters=None, **_):
        code = self._group_code(risk_group)
        if code == "invalid":
            return {"status": "invalid_input", "message": "risk_group phải là một trong: thấp, trung bình, cao (hoặc để trống)."}
        frame, applied, msg = self._apply_filters(filters)
        if msg:
            return {"status": "invalid_input", "message": msg}
        t = self.table.loc[frame.index]
        total = int(len(t))
        groups = []
        for name, (lo, hi) in self.groups.items():
            n = int((t.risk_group == name).sum())
            share = n / total if total else 0.0
            groups.append({"risk_group": GROUP_VI[name], "risk_group_code": name, "score_range": f"{lo}–{hi}",
                           "count": n, "share": round(share, 6), "share_display": vi_pct(share, 1)})
        out = {"status": "ok", "filters_applied": applied, "total_customers": total, "groups": groups, **self._base()}
        if code:
            g = next(x for x in groups if x["risk_group_code"] == code)
            out["requested_group"] = g
        if total == 0:
            out["message"] = "Không có hồ sơ nào thỏa điều kiện lọc."
        return out

    def list_customers(self, risk_group=None, limit=10, filters=None, **_):
        code = self._group_code(risk_group)
        if code == "invalid":
            return {"status": "invalid_input", "message": "risk_group phải là một trong: thấp, trung bình, cao (hoặc để trống)."}
        try:
            n = int(float(limit)) if limit not in (None, "") else 10
        except (TypeError, ValueError):
            return {"status": "invalid_input", "message": f"limit phải là số nguyên từ 1 đến {MAX_LIST}."}
        if n < 1:
            return {"status": "invalid_input", "message": f"limit phải là số nguyên từ 1 đến {MAX_LIST}."}
        capped = n > MAX_LIST
        n = min(n, MAX_LIST)
        frame, applied, msg = self._apply_filters(filters)
        if msg:
            return {"status": "invalid_input", "message": msg}
        t = self.table.loc[frame.index].copy()
        if code:
            t = t[t.risk_group == code]
        t["cid"] = t.index
        t = t.sort_values(["probability", "cid"], ascending=[False, True])
        rows = [{"rank": i + 1, "customer_id": int(cid), "probability": round(float(r.probability), 6),
                 "probability_display": vi_num(float(r.probability), 4), "score": int(r.score), "risk_group": GROUP_VI[r.risk_group]}
                for i, (cid, r) in enumerate(t.head(n).iterrows())]
        out = {"status": "ok", "risk_group": GROUP_VI.get(code) if code else "tất cả", "filters_applied": applied,
               "total_matching": int(len(t)), "returned": len(rows), "customers": rows, **self._base()}
        if capped:
            out["message"] = f"Danh sách được giới hạn tối đa {MAX_LIST} hồ sơ."
        return out

    # ---------- phục vụ đánh giá (không phải công cụ của Agent) ----------
    def score_table(self):
        t = self.table.copy()
        miss = self.crm[self.columns].isna().sum(axis=1)
        return [{"customer_id": int(cid), "probability": round(float(r.probability), 6), "score": int(r.score),
                 "risk_group_code": r.risk_group, "missing_count": int(miss.loc[cid])} for cid, r in t.iterrows()]

    TOOLS = ("get_customer", "predict_risk", "explain_customer", "count_by_group", "list_customers")

    def call(self, tool, params):
        if tool not in self.TOOLS:
            return {"status": "invalid_input", "message": f"Công cụ không hợp lệ: {tool}"}
        t0 = time.perf_counter()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            out = getattr(self, tool)(**(params or {}))
        out["tool"] = tool
        out["processing_ms"] = round(1000 * (time.perf_counter() - t0), 1)
        return out
