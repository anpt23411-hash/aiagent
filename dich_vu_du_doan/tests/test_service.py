"""Kiểm thử dịch vụ dự đoán: chạy `pytest -q` trong thư mục dich_vu_du_doan."""
import os
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

os.environ["SERVICE_API_KEY"] = "khoa-thu"
import app as appmod  # noqa: E402

client = TestClient(appmod.app)
H = {"X-API-Key": "khoa-thu"}
svc = appmod.service
HERE = os.path.dirname(__file__)


def call(tool, **body):
    r = client.post(f"/tools/{tool}", json=body, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_health_va_khoa():
    assert client.get("/health").json()["crm_records"] == 1015
    assert client.post("/tools/predict_risk", json={"customer_id": 50012}).status_code == 401
    assert client.post("/tools/predict_risk", json={"customer_id": 50012}, headers={"X-API-Key": "sai"}).status_code == 401


def test_tai_lap_du_doan_da_luu():
    ref = pd.read_csv(os.path.join(HERE, "du_doan_holdout_da_luu.csv")).set_index("CustomerID")
    t = svc.table.loc[ref.index]
    assert np.abs(t.probability.values - ref.probability.values).max() < 1e-12
    assert (t.score.values == ref.score.values).all()
    assert (t.risk_group.values == ref.risk_group.values).all()


def test_cong_thuc_diem_va_nhom():
    t = svc.table
    assert (t.score == np.minimum(10, 1 + np.floor(10 * t.probability))).all()
    assert set(t[t.score <= 2].risk_group) <= {"low"} and set(t[(t.score >= 3) & (t.score <= 5)].risk_group) <= {"medium"}
    assert set(t[t.score >= 6].risk_group) <= {"high"}


def test_predict_va_ngoai_le():
    cid = int(svc.table.index[0])
    r = call("predict_risk", customer_id=str(cid))
    assert r["status"] == "ok" and r["customer_id"] == cid and r["probability_display"].count(",") == 1
    assert r["above_threshold"] == (r["probability"] >= svc.threshold)
    assert call("predict_risk", customer_id=99999999)["status"] == "not_found"
    for bad in ["ABC", "", None, "50-12", "-5"]:
        assert call("predict_risk", customer_id=bad)["status"] == "invalid_id"


def test_ho_so_thieu_truong():
    miss = svc.crm[svc.columns].isna().any(axis=1)
    cid = int(svc.crm.index[miss][0])
    r = call("predict_risk", customer_id=cid)
    assert r["missing_fields"] and r["data_notes"]
    g = call("get_customer", customer_id=cid)
    assert set(g["missing_fields"]) == set(r["missing_fields"]) and "Churn" not in g["profile"]


def test_giai_thich_cong_tinh():
    for cid in list(svc.table.index[:20]):
        r = call("explain_customer", customer_id=int(cid), top_k=3)
        assert r["status"] == "ok" and r["additivity_check"].startswith("đạt")
        assert len(r["increasing_factors"]) <= 3 and all(f["shap"] > 0 for f in r["increasing_factors"])
        assert all(f["shap"] < 0 for f in r["decreasing_factors"])
        s = [f["shap"] for f in r["increasing_factors"]]
        assert s == sorted(s, reverse=True)


def test_thong_ke_va_danh_sach_nhat_quan():
    c = call("count_by_group")
    assert c["total_customers"] == 1015 and sum(g["count"] for g in c["groups"]) == 1015
    c3 = call("count_by_group", risk_group="cao", filters={"CityTier": 3})
    n_high_3 = int(((svc.table.risk_group == "high") & (svc.crm.CityTier == 3)).sum())
    assert c3["requested_group"]["count"] == n_high_3
    lst = call("list_customers", risk_group="cao", limit=10)
    probs = [x["probability"] for x in lst["customers"]]
    assert probs == sorted(probs, reverse=True) and lst["returned"] == 10
    top = svc.table.sort_values("probability", ascending=False).index[0]
    assert lst["customers"][0]["customer_id"] == int(top)
    assert call("list_customers", limit=500)["returned"] == 50
    assert call("count_by_group", filters={"Hacker": 1})["status"] == "invalid_input"
    assert call("count_by_group", filters={"Gender": "Robot"})["status"] == "invalid_input"
    assert call("count_by_group", filters={"Tenure": {"max": 1}})["total_customers"] > 0
    assert call("list_customers", risk_group="rat cao")["status"] == "invalid_input"


def test_cong_cu_khong_ton_tai_va_tham_so_thua():
    assert call("delete_customer", customer_id=50012)["status"] == "invalid_input"
    r = call("predict_risk", customer_id=int(svc.table.index[0]), sql="DROP TABLE")
    assert r["status"] == "ok"
