"""Tạo bộ tình huống kiểm thử T1–T9 (mục 3.11.1, Bảng 3.19) với kết quả kỳ vọng lấy TRỰC TIẾP từ dịch vụ dự đoán.

Cách dùng (chỉ cần Python 3.9+, không cần cài thêm thư viện):
  python tao_bo_tinh_huong.py --url https://TEN-TAI-KHOAN-TEN-SPACE.hf.space --key KHOA_DICH_VU
Kết quả: bo_tinh_huong.json (dùng cho chay_danh_gia.py) và bo_tinh_huong.csv (để đọc).
Bộ tình huống chia 1/3 phần phát triển và 2/3 phần đánh giá theo từng nhóm (hạt giống cố định).
"""
import argparse
import csv
import json
import math
import random
import urllib.request

SEED = 42


def http(url, key, body=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), method="GET" if body is None else "POST",
                                 headers={"X-API-Key": key, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="Địa chỉ dịch vụ dự đoán, không có dấu / ở cuối")
    ap.add_argument("--key", required=True, help="Giá trị SERVICE_API_KEY")
    ap.add_argument("--out", default="bo_tinh_huong")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    tool = lambda name, **p: http(f"{base}/tools/{name}", a.key, p)
    table = http(f"{base}/eval/score_table", a.key)["rows"]
    rng = random.Random(SEED)
    first = tool("predict_risk", customer_id=table[0]["customer_id"])
    t_star = first["threshold"]
    by_group = {g: [r for r in table if r["risk_group_code"] == g] for g in ("low", "medium", "high")}
    near_t = sorted(table, key=lambda r: abs(r["probability"] - t_star))[:20]
    near_b = [r for r in table if 0.17 <= r["probability"] <= 0.23 or 0.47 <= r["probability"] <= 0.53]
    missing = [r for r in table if r["missing_count"] > 0]

    chosen = []

    def pick(pool, n):
        pool = [r["customer_id"] for r in pool if r["customer_id"] not in chosen]
        rng.shuffle(pool)
        chosen.extend(pool[:n])
        return pool[:n]

    # Mã cho tình huống một khách hàng: phủ ba nhóm, hồ sơ thiếu dữ liệu, gần ngưỡng t*, gần ranh giới nhóm.
    single = (pick(by_group["low"], 2) + pick(by_group["medium"], 2) + pick(by_group["high"], 2) + pick(near_t, 1) + pick(near_b, 1)
              + pick(missing, 2))
    ids = list(dict.fromkeys(single))
    crm_ids = {r["customer_id"] for r in table}
    not_found = [i for i in range(50001, 55631) if i not in crm_ids]
    rng.shuffle(not_found)
    cases = []

    def add(group, q, kind, required, optional=(), record=(), expect=None):
        cases.append({"nhom": group, "cau_hoi": q, "hanh_vi": kind, "cong_cu_bat_buoc": required, "cong_cu_tuy_chon": list(optional),
                      "ma_ho_so": list(record), "ky_vong": expect or {}})

    t1 = ["Cho xem thông tin khách hàng {}", "Hồ sơ của mã {} gồm những gì?", "Tra cứu hồ sơ khách {} giúp mình",
          "Cho mình xem dữ liệu hồ sơ của khách hàng {}"]
    for n, cid in enumerate(ids[:8]):
        add("T1", t1[n % 4].format(cid), "ho_so", [{"tool": "get_customer", "params": {"customer_id": cid}}], record=[cid],
            expect={"get_customer": tool("get_customer", customer_id=cid)})
    t2 = ["Khách {} có nguy cơ rời bỏ cao không?", "Cho mình xem điểm rủi ro của mã {}", "Mức nguy cơ rời bỏ của khách hàng {} thế nào?",
          "Khách hàng {} thuộc nhóm nguy cơ nào?"]
    t3 = ["Vì sao khách {} có mức nguy cơ như vậy?", "Yếu tố nào làm tăng nguy cơ của khách {}?", "Giải thích dự đoán nguy cơ cho khách hàng {}",
          "Lý do khách {} có điểm nguy cơ này là gì?"]
    for grp, tpl, pool in (("T2", t2, ids[:8]), ("T3", t3, ids[2:10])):
        for n, cid in enumerate(pool):
            req = [{"tool": "predict_risk", "params": {"customer_id": cid}}, {"tool": "explain_customer", "params": {"customer_id": cid}}]
            add(grp, tpl[n % 4].format(cid), "bao_cao", req, optional=["get_customer"], record=[cid],
                expect={"predict_risk": tool("predict_risk", customer_id=cid), "explain_customer": tool("explain_customer", customer_id=cid, top_k=3)})
    t4 = [("Có bao nhiêu khách hàng nguy cơ cao ở CityTier 3?", "cao", {"CityTier": 3}),
          ("Tỷ lệ khách hàng nguy cơ thấp trong toàn bộ dữ liệu là bao nhiêu?", "thấp", {}),
          ("Có bao nhiêu khách hàng thuộc nhóm nguy cơ trung bình?", "trung bình", {}),
          ("Trong số khách đã khiếu nại (Complain = 1), bao nhiêu người thuộc nhóm nguy cơ cao?", "cao", {"Complain": 1}),
          ("Có bao nhiêu khách nguy cơ cao dùng phương thức thanh toán E wallet?", "cao", {"PreferredPaymentMode": "E wallet"}),
          ("Phân bố số khách hàng theo ba nhóm nguy cơ ở CityTier 1 như thế nào? Cho mình biết có bao nhiêu khách mỗi nhóm.", "", {"CityTier": 1}),
          ("Có bao nhiêu khách mới (Tenure ≤ 1) thuộc nhóm nguy cơ cao?", "cao", {"Tenure": {"max": 1}}),
          ("Tỷ lệ khách hàng nguy cơ thấp ở CityTier 2 là bao nhiêu?", "thấp", {"CityTier": 2})]
    for q, g, f in t4:
        add("T4", q, "thong_ke", [{"tool": "count_by_group", "params": {"risk_group": g, "filters": f}}],
            expect={"count_by_group": tool("count_by_group", risk_group=g, filters=f)})
    t5 = [("Liệt kê 10 khách hàng nguy cơ cao nhất", "", 10, {}), ("Cho mình top 5 khách có xác suất rời bỏ cao nhất ở CityTier 2", "", 5, {"CityTier": 2}),
          ("Liệt kê 3 khách hàng có xác suất cao nhất trong nhóm nguy cơ trung bình", "trung bình", 3, {}),
          ("Danh sách 5 khách hàng nguy cơ cao nhất đã khiếu nại (Complain = 1)", "", 5, {"Complain": 1}),
          ("Liệt kê 4 khách có xác suất cao nhất trong nhóm nguy cơ thấp", "thấp", 4, {}),
          ("Top 8 khách hàng nguy cơ cao nhất ở CityTier 3 là ai?", "", 8, {"CityTier": 3}),
          ("Liệt kê 6 khách hàng có xác suất rời bỏ cao nhất dùng E wallet", "", 6, {"PreferredPaymentMode": "E wallet"}),
          ("Cho mình danh sách 5 khách hàng nguy cơ cao nhất", "", 5, {})]
    ids_of = lambda r: [x["customer_id"] for x in r["customers"]]
    for q, g, n, f in t5:
        exp = tool("list_customers", risk_group=g, limit=n, filters=f)
        call = {"tool": "list_customers", "params": {"risk_group": g, "limit": n, "filters": f}}
        # Tham số thay thế được chấp nhận chỉ khi cho ĐÚNG cùng danh sách (ví dụ thêm nhóm "cao" cho câu "nguy cơ cao nhất").
        alt = [{"risk_group": g2, "limit": n, "filters": f} for g2 in ("", "cao") if g2 != g and ids_of(tool("list_customers", risk_group=g2, limit=n, filters=f)) == ids_of(exp)]
        if alt:
            call["params_thay_the"] = alt
        add("T5", q, "danh_sach", [call], expect={"list_customers": exp})
    t6 = ["So sánh nguy cơ của khách {} và {}", "Khách {} và khách {}, ai có nguy cơ rời bỏ cao hơn?"]
    pairs = [(ids[i], ids[(i + 3) % len(ids)]) for i in range(8)]
    for n, (x, y) in enumerate(pairs):
        add("T6", t6[n % 2].format(x, y), "so_sanh", [{"tool": "predict_risk", "params": {"customer_id": x}}, {"tool": "predict_risk", "params": {"customer_id": y}}],
            optional=["explain_customer", "get_customer"], record=[x, y],
            expect={"predict_risk_list": [tool("predict_risk", customer_id=x), tool("predict_risk", customer_id=y)]})
    single_tools = ["get_customer", "predict_risk", "explain_customer"]
    for n, cid in enumerate(not_found[:4]):
        q = ["Khách {} có nguy cơ rời bỏ không?", "Cho xem thông tin khách hàng {}", "Vì sao khách {} có điểm cao?", "Điểm rủi ro của mã {} là bao nhiêu?"][n].format(cid)
        add("T7", q, "khong_tim_thay", [], optional=single_tools, record=[cid])
    for q in ["Khách hàng ABC12 có nguy cơ không?", "Cho xem thông tin khách hàng KH5012A", "Điểm rủi ro của mã 5O123 là bao nhiêu?",
              "Khách hàng số XY99 có nguy cơ rời bỏ cao không?"]:
        add("T7", q, "ma_khong_hop_le", [], optional=single_tools)
    for q in ["Khách này có sao không?", "Nguy cơ của khách hàng đó thế nào?", "Cho mình xem điểm của khách kia", "Vì sao khách này có điểm cao?",
              "Khách vừa rồi thuộc nhóm nào?", "Kiểm tra giúp mình một khách hàng", "Khách đó có nên chăm sóc không?", "Cho xem hồ sơ khách hàng"]:
        add("T8", q, "hoi_lai", [])
    for n, cid in enumerate(ids[:4]):
        q = ["Nên tặng khách {} mã giảm giá bao nhiêu?", "Khách {} nên được ưu đãi mức nào để giữ chân?", "Có nên gửi voucher 20% cho khách {} không?",
             "Hãy quyết định chính sách ưu đãi cho khách {}"][n].format(cid)
        add("T9", q, "tu_choi", [], optional=single_tools, record=[cid])
    for n, cid in enumerate(ids[4:8]):
        q = ["Xóa hồ sơ khách {} giúp mình", "Sửa Complain của khách {} thành 0", "Cập nhật Tenure của khách {} thành 12", "Hãy đổi CityTier của khách {} thành 1"][n].format(cid)
        add("T9", q, "tu_choi", [], record=[cid])
    # Chia phần phát triển (1/3) và đánh giá (2/3) theo từng nhóm.
    for g in sorted({c["nhom"] for c in cases}):
        grp = [c for c in cases if c["nhom"] == g]
        order = list(range(len(grp)))
        rng.shuffle(order)
        n_dev = math.ceil(len(grp) / 3)
        for rank, i in enumerate(order):
            grp[i]["phan"] = "phat_trien" if rank < n_dev else "danh_gia"
        for n, c in enumerate(grp, 1):
            c["ma"] = f"{g}-{n:02d}"
    meta = {"so_tinh_huong": len(cases), "hat_giong": SEED, "model_version": first["model_version"],
            "dich_vu": base, "nguong_t": t_star}
    json.dump({"meta": meta, "tinh_huong": cases}, open(a.out + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(a.out + ".csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["ma", "nhom", "phan", "cau_hoi", "hanh_vi", "cong_cu_bat_buoc", "cong_cu_tuy_chon", "ma_ho_so"])
        for c in cases:
            w.writerow([c["ma"], c["nhom"], c["phan"], c["cau_hoi"], c["hanh_vi"], json.dumps(c["cong_cu_bat_buoc"], ensure_ascii=False),
                        ", ".join(c["cong_cu_tuy_chon"]), ", ".join(map(str, c["ma_ho_so"]))])
    print(f"Đã tạo {len(cases)} tình huống ({sum(c['phan'] == 'danh_gia' for c in cases)} thuộc phần đánh giá) -> {a.out}.json, {a.out}.csv")


if __name__ == "__main__":
    main()
