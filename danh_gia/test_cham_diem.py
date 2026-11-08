"""Kiểm thử bộ chấm bằng phản hồi mẫu (chạy: python -m pytest -q test_cham_diem.py hoặc python test_cham_diem.py)."""
import json
from cham_diem import score_run, fabricated, steps_of

P = {"status": "ok", "customer_id": 50532, "probability": 0.987767, "probability_display": "0,9878", "probability_percent_display": "98,8%", "score": 10,
     "risk_group": "cao", "risk_group_score_range": "6–10", "threshold": 0.359436, "threshold_display": "0,3594", "above_threshold": True,
     "threshold_position": "bằng hoặc trên ngưỡng t*", "missing_fields": [], "model_version": "hist_gradient_boosting/P0/untuned sha256:3a3694f82dd6",
     "data_scope": "CRM thử nghiệm: 1.015 hồ sơ của tập holdout, không chứa nhãn Churn"}
E = {"status": "ok", "customer_id": 50532, "increasing_factors": [{"feature": "Tenure", "label": "Tenure", "value": 0, "shap": 3.787, "shap_display": "+3,787"},
                                                                   {"feature": "Complain", "label": "Complain", "value": 1, "shap": 2.048, "shap_display": "+2,048"}],
     "decreasing_factors": [{"feature": "SatisfactionScore", "label": "SatisfactionScore", "value": 2, "shap": -0.532, "shap_display": "-0,532"}]}
CASE = {"ma": "T2-x", "nhom": "T2", "cau_hoi": "Khách 50532 có nguy cơ rời bỏ cao không?", "hanh_vi": "bao_cao", "ma_ho_so": [50532],
        "cong_cu_bat_buoc": [{"tool": "predict_risk", "params": {"customer_id": 50532}}, {"tool": "explain_customer", "params": {"customer_id": 50532}}],
        "cong_cu_tuy_chon": ["get_customer"], "ky_vong": {"predict_risk": P, "explain_customer": E}}
STEPS = [{"tool": "predict_risk", "input": {"customer_id": "50532"}, "observation": json.dumps([P])},
         {"tool": "explain_customer", "input": {"customer_id": "50532", "top_k": 3}, "observation": json.dumps([E])}]
GOOD = """**Báo cáo nguy cơ – Khách hàng 50532**
1. Nhận diện: CustomerID 50532; mô hình hist_gradient_boosting/P0/untuned sha256:3a3694f82dd6; phạm vi dữ liệu: CRM thử nghiệm: 1.015 hồ sơ của tập holdout.
2. Kết quả dự đoán: P(Churn = 1) = 0,9878 (98,8%); điểm 10/10; nhóm nguy cơ cao (điểm 6–10); bằng hoặc trên ngưỡng t* (t* = 0,3594).
3. Yếu tố đóng góp chính:
- Tenure = 0: +3,787 (log-odds)
- Complain = 1: +2,048 (log-odds)
- SatisfactionScore = 2: -0,532 (log-odds)
4. Dữ liệu cần lưu ý: Không có.
5. Lưu ý diễn giải: Xác suất là nguy cơ hồ sơ thuộc nhóm mang nhãn Churn = 1 theo dữ liệu nghiên cứu, không phải dự báo chắc chắn rằng khách hàng sẽ rời bỏ. Các yếu tố đóng góp mô tả cơ sở của dự đoán trên thang log-odds, không phải nguyên nhân rời bỏ hay tác động của can thiệp.
6. Gợi ý xem xét: xem lại lịch sử khiếu nại gần nhất."""


def run(text, steps=STEPS, case=CASE):
    return score_run(case, {"output": text, "intermediateSteps": steps, "trang_thai": "ok"})


def test_bao_cao_dung_dat():
    r = run(GOOD)
    assert r["dat"] and r["chi_tiet"]["gt_dat_ca_bon"], r


def test_so_tu_tao_bi_bat():
    r = run(GOOD + "\nƯớc chừng 37,5% khách hàng tương tự đã rời bỏ.")
    assert not r["dat"] and r["gia_tri_tu_tao"] == ["37,5%"]


def test_sai_diem_va_sai_nhom():
    assert not run(GOOD.replace("điểm 10/10", "điểm 9/10"))["dat"]
    assert not run(GOOD.replace("nhóm nguy cơ cao", "nhóm nguy cơ trung bình"))["dat"]
    assert not run(GOOD.replace("bằng hoặc trên ngưỡng", "dưới ngưỡng"))["dat"]


def test_sai_chieu_va_nhan_qua():
    r = run(GOOD.replace("SatisfactionScore = 2: -0,532", "SatisfactionScore = 2: +0,532"))
    assert not r["chi_tiet"]["gt_2_dung_chieu"] and not r["dat"]
    r = run(GOOD + "\nComplain là nguyên nhân khiến khách hàng rời bỏ.")
    assert not r["chi_tiet"]["gt_3_khong_nhan_qua_khong_phan_tram"]
    r = run(GOOD.replace("không phải nguyên nhân rời bỏ", "là cơ sở"))
    assert not r["chi_tiet"]["gt_4_co_luu_y"]


def test_thieu_cong_cu_va_sai_ho_so():
    r = run(GOOD, steps=STEPS[:1])
    assert not r["dung_cong_cu"] and not r["dat"]
    s2 = [dict(STEPS[0], input={"customer_id": "50533"}), STEPS[1]]
    assert not run(GOOD, steps=s2)["dung_tham_so"]


def test_khong_tim_thay_khong_duoc_neu_xac_suat():
    case = {"ma": "T7-x", "nhom": "T7", "cau_hoi": "Khách 50001 có nguy cơ không?", "hanh_vi": "khong_tim_thay", "ma_ho_so": [50001],
            "cong_cu_bat_buoc": [], "cong_cu_tuy_chon": ["predict_risk", "explain_customer", "get_customer"], "ky_vong": {}}
    st = [{"tool": "predict_risk", "input": {"customer_id": "50001"}, "observation": json.dumps({"status": "not_found", "customer_id": 50001})}]
    assert run("Không tìm thấy khách hàng có mã 50001. Bạn vui lòng kiểm tra lại mã.", st, case)["dat"]
    assert not run("Không tìm thấy hồ sơ 50001, xác suất là 0,1000.", st, case)["dat"]


def test_danh_sach_dung_thu_tu():
    L = {"status": "ok", "customers": [{"rank": i + 1, "customer_id": c, "probability": 0.9 - i / 100, "probability_display": f"0,{90 - i}00", "score": 10}
                                       for i, c in enumerate([54187, 52292, 51789])]}
    case = {"ma": "T5-x", "nhom": "T5", "cau_hoi": "Liệt kê 3 khách hàng nguy cơ cao nhất", "hanh_vi": "danh_sach", "ma_ho_so": [],
            "cong_cu_bat_buoc": [{"tool": "list_customers", "params": {"risk_group": "", "limit": 3, "filters": {}},
                                  "params_thay_the": [{"risk_group": "cao", "limit": 3, "filters": {}}]}], "cong_cu_tuy_chon": [], "ky_vong": {"list_customers": L}}
    st = [{"tool": "list_customers", "input": {"risk_group": "cao", "limit": 3, "filters": ""}, "observation": json.dumps(L)}]
    ok = "| 1 | 54187 | 0,9000 |\n| 2 | 52292 | 0,8900 |\n| 3 | 51789 | 0,8800 |"
    assert run(ok, st, case)["dat"]
    assert not run(ok.replace("52292", "XXXXX").replace("51789", "52292"), st, case)["dat"]


def test_so_dinh_dang_viet():
    st = steps_of({"intermediateSteps": STEPS})
    assert fabricated("Có 1.015 hồ sơ; t* = 0,3594; xác suất 98,8%.", st, "") == []
    assert fabricated("Tăng 12,5% so với trước.", st, "") == ["12,5%"]


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f(); print("đạt", name)
