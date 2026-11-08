"""Chạy bộ tình huống qua Webhook kiểm thử của workflow n8n, lặp k lần, chấm điểm và tổng hợp chỉ số (mục 3.11, Bảng 3.20).

Cách dùng (Python 3.9+, không cần cài thêm thư viện):
  python chay_danh_gia.py --webhook https://TEN.app.n8n.cloud/webhook/kltn-agent-kiem-thu --khoa-kiem-thu GIA_TRI_HEADER --k 3
Tùy chọn:
  --phan danh_gia | phat_trien | tat_ca     (mặc định: danh_gia, tức phần đánh giá cố định)
  --gioi-han 5                              (chỉ chạy 5 tình huống đầu, để thử)
  --n8n-api-url https://TEN.app.n8n.cloud --n8n-api-key ...   (nếu gói n8n có API: lấy token và thời gian của LLM)
  --don-gia-vao 2 --don-gia-ra 8            (USD cho 1 triệu token vào/ra, theo bảng giá tại ngày đánh giá)
Kết quả ghi vào thư mục --out: ket_qua_tho.jsonl, ket_qua_tung_lan.csv, tong_hop.json, tong_hop.md, cham_giai_thich_thu_cong.csv.
Chạy lại cùng lệnh sẽ bỏ qua các lần chạy đã có trong ket_qua_tho.jsonl.
"""
import argparse
import csv
import json
import os
import statistics
import time
import urllib.error
import urllib.request
import uuid

from cham_diem import score_run, steps_of


def post(url, header_name, header_value, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={header_name: header_value, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def n8n_execution(api_url, api_key, execution_id):
    req = urllib.request.Request(f"{api_url.rstrip('/')}/api/v1/executions/{execution_id}?includeData=true", headers={"X-N8N-API-KEY": api_key})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    run = d.get("data", {}).get("resultData", {}).get("runData", {})
    tok_in = tok_out = 0
    llm_ms = 0
    for r in run.get("OpenAI Chat Model", []):
        llm_ms += r.get("executionTime", 0)
        try:
            u = r["data"]["ai_languageModel"][0][0]["json"].get("tokenUsage") or {}
        except (KeyError, IndexError, TypeError):
            u = {}
        tok_in += u.get("promptTokens", 0)
        tok_out += u.get("completionTokens", 0)
    tool_ms = sum(r.get("executionTime", 0) for name in ("get_customer", "predict_risk", "explain_customer", "count_by_group", "list_customers")
                  for r in run.get(name, []))
    return {"token_vao": tok_in, "token_ra": tok_out, "thoi_gian_llm_ms": llm_ms, "thoi_gian_cong_cu_n8n_ms": tool_ms}


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    i = (len(xs) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def rate(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(bool(x) for x in xs) / len(xs), 4) if xs else None


def summarize(rows, k, price_in, price_out):
    def block(rs):
        cases = {}
        for r in rs:
            cases.setdefault(r["ma"], []).append(r["dat"])
        full = [v for v in cases.values() if len(v) >= k]
        lat = [r["thoi_gian_ms"] for r in rs if r["thoi_gian_ms"] is not None]
        tool = [r["thoi_gian_dich_vu_ms"] for r in rs if r["thoi_gian_dich_vu_ms"] is not None]
        llm = [r["thoi_gian_llm_ms"] for r in rs if r.get("thoi_gian_llm_ms") is not None]
        tin = [r["token_vao"] for r in rs if r.get("token_vao") is not None]
        tout = [r["token_ra"] for r in rs if r.get("token_ra") is not None]
        out = {"so_tinh_huong": len(cases), "so_lan_chay": len(rs),
               "ty_le_dung_cong_cu": rate(r["dung_cong_cu"] for r in rs), "ty_le_dung_tham_so": rate(r["dung_tham_so"] for r in rs),
               "ty_le_dung_ho_so": rate(r["dung_ho_so"] for r in rs), "loi_goi_thua_tb": round(statistics.mean(r["so_loi_goi_thua"] for r in rs), 3) if rs else None,
               "ty_le_khop_gia_tri": rate(r["khop_gia_tri"] for r in rs), "tong_gia_tri_tu_tao": sum(r["so_gia_tri_tu_tao"] for r in rs),
               "so_lan_co_gia_tri_tu_tao": sum(r["so_gia_tri_tu_tao"] > 0 for r in rs),
               "ty_le_hoan_thanh_moi_lan": rate(r["dat"] for r in rs),
               f"pass^{k}": round(sum(all(v[:k]) for v in full) / len(full), 4) if full else None,
               "thoi_gian_ms_trung_vi": pct(lat, 0.5), "thoi_gian_ms_p95": pct(lat, 0.95),
               "thoi_gian_xu_ly_dich_vu_ms_trung_vi": pct(tool, 0.5)}
        rub = [r for r in rs if r.get("gt_dat_ca_bon") is not None]
        if rub:
            for c in ("gt_1_yeu_to_dung", "gt_2_dung_chieu", "gt_3_khong_nhan_qua_khong_phan_tram", "gt_4_co_luu_y", "gt_dat_ca_bon"):
                out["ty_le_" + c] = rate(r[c] for r in rub)
        if llm:
            out["thoi_gian_llm_ms_trung_vi"] = pct(llm, 0.5)
        if tin:
            out["token_vao_tb"], out["token_ra_tb"] = round(statistics.mean(tin), 1), round(statistics.mean(tout), 1)
            if price_in is not None and price_out is not None:
                out["chi_phi_usd_tb"] = round((statistics.mean(tin) * price_in + statistics.mean(tout) * price_out) / 1e6, 6)
        return out
    groups = sorted({r["nhom"] for r in rows})
    res = {"tong": block(rows), "theo_nhom": {g: block([r for r in rows if r["nhom"] == g]) for g in groups}}
    exc = [r for r in rows if r["nhom"] in ("T7", "T8", "T9")]
    if exc:
        res["ty_le_xu_ly_dung_T7_T9"] = rate(r["dat"] for r in exc)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--webhook", required=True)
    ap.add_argument("--khoa-kiem-thu", default=os.environ.get("KLTN_KHOA_KIEM_THU", ""), help="Giá trị header của credential Webhook kiểm thử")
    ap.add_argument("--ten-header", default="X-Test-Key")
    ap.add_argument("--bo-tinh-huong", default="bo_tinh_huong.json")
    ap.add_argument("--phan", default="danh_gia", choices=["danh_gia", "phat_trien", "tat_ca"])
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--gioi-han", type=int, default=0)
    ap.add_argument("--nghi", type=float, default=1.0, help="Số giây nghỉ giữa hai yêu cầu")
    ap.add_argument("--thoi-gian-cho", type=int, default=180)
    ap.add_argument("--out", default="ket_qua_danh_gia")
    ap.add_argument("--n8n-api-url", default=os.environ.get("N8N_API_URL", ""))
    ap.add_argument("--n8n-api-key", default=os.environ.get("N8N_API_KEY", ""))
    ap.add_argument("--ten-mo-hinh", default="", help="Tên và phiên bản LLM ghi kèm kết quả")
    ap.add_argument("--don-gia-vao", type=float, default=None)
    ap.add_argument("--don-gia-ra", type=float, default=None)
    a = ap.parse_args()
    data = json.load(open(a.bo_tinh_huong, encoding="utf-8"))
    cases = [c for c in data["tinh_huong"] if a.phan == "tat_ca" or c["phan"] == a.phan]
    if a.gioi_han:
        cases = cases[:a.gioi_han]
    os.makedirs(a.out, exist_ok=True)
    raw_path = os.path.join(a.out, "ket_qua_tho.jsonl")
    done = set()
    if os.path.exists(raw_path):
        for line in open(raw_path, encoding="utf-8"):
            d = json.loads(line)
            done.add((d["ma"], d["lan"]))
    total = len(cases) * a.k
    n = 0
    with open(raw_path, "a", encoding="utf-8") as raw:
        for lan in range(1, a.k + 1):
            for c in cases:
                n += 1
                if (c["ma"], lan) in done:
                    continue
                body = {"chatInput": c["cau_hoi"], "sessionId": f"{c['ma']}-lan{lan}-{uuid.uuid4().hex[:8]}"}
                t0 = time.perf_counter()
                try:
                    resp, err = post(a.webhook, a.ten_header, a.khoa_kiem_thu, body, a.thoi_gian_cho), ""
                except (urllib.error.URLError, TimeoutError, ValueError) as e:
                    resp, err = {}, str(e)[:300]
                ms = round(1000 * (time.perf_counter() - t0), 1)
                extra = {}
                if a.n8n_api_url and a.n8n_api_key and resp.get("executionId"):
                    try:
                        extra = n8n_execution(a.n8n_api_url, a.n8n_api_key, resp["executionId"])
                    except Exception as e:  # API không có trong mọi gói n8n
                        extra = {"loi_api_n8n": str(e)[:200]}
                raw.write(json.dumps({"ma": c["ma"], "lan": lan, "thoi_gian_ms": ms, "loi_ket_noi": err, "phan_hoi": resp, **extra}, ensure_ascii=False) + "\n")
                raw.flush()
                print(f"[{n}/{total}] {c['ma']} lần {lan}: {ms:.0f} ms {'LỖI ' + err if err else resp.get('trang_thai', '')}", flush=True)
                time.sleep(a.nghi)
    # Chấm lại toàn bộ từ dữ liệu thô (có thể chạy lại sau khi sửa quy tắc chấm mà không gọi lại Agent).
    by_ma = {c["ma"]: c for c in cases}
    rows, manual = [], []
    for line in open(raw_path, encoding="utf-8"):
        d = json.loads(line)
        c = by_ma.get(d["ma"])
        if not c or d["lan"] > a.k:
            continue
        resp = d["phan_hoi"] or {}
        s = score_run(c, resp) if not d["loi_ket_noi"] else {"dung_cong_cu": False, "dung_tham_so": False, "dung_ho_so": False, "so_loi_goi": 0,
                                                              "so_loi_goi_thua": 0, "khop_gia_tri": False, "chi_tiet": {"loi_ket_noi": d["loi_ket_noi"]},
                                                              "gia_tri_tu_tao": [], "so_gia_tri_tu_tao": 0, "dat": False, "cong_cu_da_goi": []}
        svc_ms = sum(float(st["obs"].get("processing_ms") or 0) for st in steps_of(resp)) if resp else None
        row = {"ma": c["ma"], "nhom": c["nhom"], "phan": c["phan"], "lan": d["lan"], "dat": s["dat"], "dung_cong_cu": s["dung_cong_cu"],
               "dung_tham_so": s["dung_tham_so"], "dung_ho_so": s["dung_ho_so"], "so_loi_goi": s["so_loi_goi"], "so_loi_goi_thua": s["so_loi_goi_thua"],
               "khop_gia_tri": s["khop_gia_tri"], "so_gia_tri_tu_tao": s["so_gia_tri_tu_tao"], "gia_tri_tu_tao": " ".join(s["gia_tri_tu_tao"]),
               "cong_cu_da_goi": ",".join(s["cong_cu_da_goi"]), "trang_thai": resp.get("trang_thai", ""), "thoi_gian_ms": d["thoi_gian_ms"],
               "thoi_gian_dich_vu_ms": svc_ms, "thoi_gian_llm_ms": d.get("thoi_gian_llm_ms"), "token_vao": d.get("token_vao"), "token_ra": d.get("token_ra"),
               "executionId": resp.get("executionId", ""), "chi_tiet": json.dumps(s["chi_tiet"], ensure_ascii=False)}
        for key in ("gt_1_yeu_to_dung", "gt_2_dung_chieu", "gt_3_khong_nhan_qua_khong_phan_tram", "gt_4_co_luu_y", "gt_dat_ca_bon"):
            row[key] = s["chi_tiet"].get(key)
        rows.append(row)
        if row["gt_dat_ca_bon"] is not None:
            manual.append({"ma": c["ma"], "lan": d["lan"], "cau_hoi": c["cau_hoi"], "phan_hoi": resp.get("output", ""),
                           "tu_dong_tc1": row["gt_1_yeu_to_dung"], "tu_dong_tc2": row["gt_2_dung_chieu"], "tu_dong_tc3": row["gt_3_khong_nhan_qua_khong_phan_tram"],
                           "tu_dong_tc4": row["gt_4_co_luu_y"], "nguoi_cham_tc1": "", "nguoi_cham_tc2": "", "nguoi_cham_tc3": "", "nguoi_cham_tc4": "", "ghi_chu": ""})
    with open(os.path.join(a.out, "ket_qua_tung_lan.csv"), "w", newline="", encoding="utf-8-sig") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
    with open(os.path.join(a.out, "cham_giai_thich_thu_cong.csv"), "w", newline="", encoding="utf-8-sig") as f:
        if manual:
            w = csv.DictWriter(f, fieldnames=list(manual[0]))
            w.writeheader(); w.writerows(manual)
    summ = summarize(rows, a.k, a.don_gia_vao, a.don_gia_ra)
    summ["cau_hinh"] = {"phan": a.phan, "k": a.k, "so_tinh_huong": len(cases), "webhook": a.webhook, "mo_hinh_llm": a.ten_mo_hinh,
                        "ngay_danh_gia": time.strftime("%Y-%m-%d"), "model_version_dich_vu": data["meta"].get("model_version"),
                        "phien_ban_chi_dan": next((json.loads(l)["phan_hoi"].get("phien_ban_chi_dan") for l in open(raw_path, encoding="utf-8")), None)}
    json.dump(summ, open(os.path.join(a.out, "tong_hop.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    keys = ["so_tinh_huong", "so_lan_chay", "ty_le_dung_cong_cu", "ty_le_dung_tham_so", "ty_le_dung_ho_so", "loi_goi_thua_tb", "ty_le_khop_gia_tri",
            "tong_gia_tri_tu_tao", "ty_le_hoan_thanh_moi_lan", f"pass^{a.k}", "thoi_gian_ms_trung_vi", "thoi_gian_ms_p95"]
    md = [f"# Tổng hợp đánh giá AI Agent ({summ['cau_hinh']['ngay_danh_gia']})", "",
          f"Phần: {a.phan}; k = {a.k}; LLM: {a.ten_mo_hinh or '(chưa ghi)'}; mô hình dự đoán: {summ['cau_hinh']['model_version_dich_vu']}; "
          f"chỉ dẫn hệ thống: {summ['cau_hinh']['phien_ban_chi_dan']}.", "",
          "| Nhóm | " + " | ".join(keys) + " |", "|" + "---|" * (len(keys) + 1)]
    for g, b in list(summ["theo_nhom"].items()) + [("Tổng", summ["tong"])]:
        md.append(f"| {g} | " + " | ".join("" if b.get(k) is None else str(b.get(k)) for k in keys) + " |")
    if "ty_le_xu_ly_dung_T7_T9" in summ:
        md += ["", f"Tỷ lệ xử lý đúng ngoại lệ T7–T9: {summ['ty_le_xu_ly_dung_T7_T9']}"]
    md += ["", "Ghi chú: tiêu chí giải thích (gt_*) được chấm tự động sơ bộ; cần người chấm xác nhận trong cham_giai_thich_thu_cong.csv.",
           "Thời gian xử lý dịch vụ là thời gian tính toán bên trong dịch vụ dự đoán, chưa gồm mạng và n8n."]
    open(os.path.join(a.out, "tong_hop.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(json.dumps(summ["tong"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
