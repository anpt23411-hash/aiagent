"""Chấm một lần chạy của Agent theo mục 3.11 (Bảng 3.20). Chỉ dùng thư viện chuẩn của Python.

Lớp 1 (3.11.2): đúng công cụ, đúng tham số, đúng hồ sơ, số lời gọi thừa.
Lớp 2 (3.11.3): khớp giá trị định lượng với kết quả kỳ vọng; đếm số giá trị tự tạo.
Giải thích (3.11.4): bốn tiêu chí có/không, chấm tự động sơ bộ, cần người chấm xác nhận.
Một lần chạy đạt khi qua lớp 1, lớp 2 và không có giá trị tự tạo.
"""
import json
import re

FEATURES = ["Tenure", "PreferredLoginDevice", "CityTier", "WarehouseToHome", "PreferredPaymentMode", "Gender", "HourSpendOnApp",
            "NumberOfDeviceRegistered", "PreferedOrderCat", "SatisfactionScore", "MaritalStatus", "NumberOfAddress", "Complain",
            "OrderAmountHikeFromlastYear", "CouponUsed", "OrderCount", "DaySinceLastOrder", "CashbackAmount"]
DERIVED = ["TenureMissing", "WarehouseToHomeMissing", "OrderAmountHikeFromlastYearMissing", "CouponUsedMissing", "OrderCountMissing", "IsNewCustomer"]
CONSTANTS = {1.0, 2.0, 3.0, 5.0, 6.0, 10.0}          # điểm 1–10 và ranh giới nhóm 1–2, 3–5, 6–10 trong mẫu báo cáo
NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+−]?\d[\d.,]*%?(?![A-Za-z_])")
GROUPS = {"low": "thấp", "medium": "trung bình", "high": "cao"}


# ---------------- tiện ích ----------------
def parse_observation(obs):
    if isinstance(obs, (dict, list)):
        o = obs
    else:
        try:
            o = json.loads(obs)
        except (TypeError, ValueError):
            return {"status": "khong_doc_duoc", "raw": str(obs)[:200]}
    if isinstance(o, list):
        o = o[0] if o else {}
    return o if isinstance(o, dict) else {}


def steps_of(response):
    out = []
    for s in response.get("intermediateSteps") or []:
        inp = s.get("input") or {}
        if isinstance(inp, str):
            try:
                inp = json.loads(inp)
            except ValueError:
                inp = {"raw": inp}
        out.append({"tool": s.get("tool"), "input": inp, "obs": parse_observation(s.get("observation"))})
    return out


def to_number(tok):
    """'0,5921' -> 0.5921; '1.015' -> 1015; '20,4%' -> (20.4, True). Trả về (giá trị, có_phần_trăm) hoặc None."""
    t = tok.replace("−", "-").rstrip(".,")
    pct = t.endswith("%")
    t = t.rstrip("%").rstrip(".,")
    if not re.search(r"\d", t):
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"[-+]?\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        return float(t), pct
    except ValueError:
        return None


def numbers_in(text):
    vals = []
    for line in str(text).split("\n"):
        line = re.sub(r"^\s*(?:[-*]\s*)?\d+[.)]\s+", "", line)          # bỏ số thứ tự đầu dòng
        for m in NUM_RE.finditer(line):
            v = to_number(m.group(0))
            if v is not None:
                vals.append((m.group(0), v[0], v[1]))
    return vals


def allowed_numbers(steps, question):
    base = set(CONSTANTS)

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            base.add(float(x))
        elif isinstance(x, str):
            for _, v, _p in numbers_in(x):
                base.add(v)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for s in steps:
        walk(s["obs"])
    for _, v, _p in numbers_in(question):
        base.add(v)
    return base


def is_allowed(v, pct, base):
    for a in base:
        if abs(v - a) < 1e-9:
            return True
        for d in range(0, 5):
            if abs(v - round(a, d)) < 1e-9 or (pct and 0 <= a <= 1 and abs(v - round(100 * a, max(0, d - 2))) < 1e-9):
                return True
    return False


def fabricated(response_text, steps, question):
    base = allowed_numbers(steps, question)
    return [tok for tok, v, pct in numbers_in(response_text) if not is_allowed(v, pct, base)]


def norm_group(g):
    if g in (None, ""):
        return ""
    g = str(g).strip().lower().replace("_", " ")
    g = re.sub(r"^(nhóm|nguy cơ)\s+", "", g)
    return {"low": "thấp", "thap": "thấp", "medium": "trung bình", "trung binh": "trung bình", "high": "cao"}.get(g, g)


def norm_filters(f):
    if f in (None, "", {}):
        return {}
    if isinstance(f, str):
        try:
            f = json.loads(f)
        except ValueError:
            return {"__khong_hop_le__": f}
    out = {}
    for k, v in (f or {}).items():
        if isinstance(v, dict):
            v = {kk: float(vv) for kk, vv in v.items()}
        elif isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\d+(\.\d+)?", v.strip())):
            v = float(v)
        else:
            v = str(v).strip().lower()
        out[str(k).strip().lower()] = v
    return out


def same_params(expected, given):
    for k, v in expected.items():
        g = given.get(k)
        if k == "customer_id":
            if str(g).strip() != str(v):
                return False
        elif k == "risk_group":
            if norm_group(g) != norm_group(v):
                return False
        elif k == "limit":
            try:
                if int(float(g if g not in (None, "") else 10)) != int(v):
                    return False
            except (TypeError, ValueError):
                return False
        elif k == "filters":
            if norm_filters(g) != norm_filters(v):
                return False
    return True


def ids_in(text):
    return [int(x) for x in re.findall(r"(?<![\d,.])5\d{4}(?![\d,])", str(text))]


# ---------------- lớp 1 ----------------
def layer1(case, steps):
    req, opt = case["cong_cu_bat_buoc"], set(case.get("cong_cu_tuy_chon", []))
    used = [False] * len(steps)
    tool_ok, param_ok = True, True

    def ok_params(r, given):
        return any(same_params(p, given) for p in [r["params"]] + r.get("params_thay_the", []))
    for r in req:
        idx = next((i for i, s in enumerate(steps) if not used[i] and s["tool"] == r["tool"] and ok_params(r, s["input"])), None)
        if idx is None:
            idx = next((i for i, s in enumerate(steps) if not used[i] and s["tool"] == r["tool"]
                        and same_params({k: v for k, v in r["params"].items() if k == "customer_id"}, s["input"])), None)
        if idx is None:
            idx = next((i for i, s in enumerate(steps) if not used[i] and s["tool"] == r["tool"]), None)
        if idx is None:
            tool_ok = param_ok = False
            continue
        used[idx] = True
        if not ok_params(r, steps[idx]["input"]):
            param_ok = False
    seen, extra = set(), 0
    for i, s in enumerate(steps):
        key = (s["tool"], json.dumps(s["input"], sort_keys=True, ensure_ascii=False))
        if not used[i] and (s["tool"] not in opt or key in seen):
            extra += 1
        seen.add(key)
    if any(not used[i] and s["tool"] not in opt for i, s in enumerate(steps)):
        tool_ok = False
    exp_ids = case.get("ma_ho_so", [])
    called_ids = {str(s["input"].get("customer_id")).strip() for s in steps if "customer_id" in s["input"]}
    record_ok = None
    if exp_ids and (req or called_ids):
        record_ok = bool(called_ids) and called_ids <= {str(i) for i in exp_ids}
    return {"dung_cong_cu": tool_ok, "dung_tham_so": param_ok and tool_ok, "dung_ho_so": record_ok,
            "so_loi_goi": len(steps), "so_loi_goi_thua": extra}


# ---------------- lớp 2 và giải thích ----------------
def has_prob(text, p):
    return p["probability_display"] in text or p["probability_percent_display"] in text


def has_score(text, s):
    pats = [rf"(?<!\d){s}\s*/\s*10(?!\d)", rf"điểm[^\d\n]{{0,25}}(?<!\d){s}(?![\d,])"]
    return any(re.search(x, text, re.I) for x in pats)


def has_group(text, g):
    m = re.findall(r"nhóm(?:\s+nguy cơ)?\s*[:\-]?\s*\**\s*(thấp|trung bình|cao)", text, re.I)
    if m:
        return all(x.lower() == g for x in m[:1])
    m = re.findall(r"nguy cơ\s+\**(thấp|trung bình|cao)\**", text, re.I)
    return bool(m) and m[0].lower() == g


def has_threshold(text, above):
    t = text.lower()
    return ("trên ngưỡng" in t and "dưới ngưỡng" not in t) if above else ("dưới ngưỡng" in t and "trên ngưỡng" not in t)


def explanation_rubric(text, exp):
    names = {f["feature"]: f for f in exp["increasing_factors"] + exp["decreasing_factors"]}
    known = FEATURES + DERIVED
    lines = [l for l in text.split("\n") if re.search(r"[+\-−]\d+,\d{2,}|log-odds|làm tăng|làm giảm", l)]
    mentioned, sign_ok = set(), True
    for l in lines:
        for f in sorted(known, key=len, reverse=True):
            if re.search(rf"(?<![A-Za-z]){f}(?![A-Za-z])", l):
                mentioned.add(f)
                if f in names:
                    m = re.search(r"([+\-−])\d+,\d{2,}", l)
                    if m:
                        sign_ok &= (m.group(1) == "+") == (names[f]["shap"] > 0)
                    elif re.search(r"làm tăng", l) or re.search(r"làm giảm", l):
                        sign_ok &= bool(re.search(r"làm tăng", l)) == (names[f]["shap"] > 0)
                break
    c1 = bool(mentioned) and mentioned <= set(names)
    t = text.lower()
    causal = re.search(r"(?<!không phải )(là nguyên nhân|gây ra việc rời bỏ|khiến (?:khách hàng|khách) rời bỏ|dẫn đến (?:việc )?rời bỏ)", t)
    pct_shap = any(re.search(r"[+\-−]\d+,\d+\s*%", l) for l in lines)
    c3 = not causal and not pct_shap
    c4 = "không phải dự báo chắc chắn" in t and "không phải nguyên nhân" in t
    return {"gt_1_yeu_to_dung": c1, "gt_2_dung_chieu": c1 and sign_ok, "gt_3_khong_nhan_qua_khong_phan_tram": c3,
            "gt_4_co_luu_y": c4, "gt_dat_ca_bon": c1 and sign_ok and c3 and c4, "gt_yeu_to_nhac_den": sorted(mentioned)}


def layer2(case, text, steps):
    k, kind = case.get("ky_vong", {}), case["hanh_vi"]
    detail = {}
    if kind == "bao_cao":
        p = k["predict_risk"]
        detail = {"xac_suat": has_prob(text, p), "diem": has_score(text, p["score"]), "nhom": has_group(text, p["risk_group"]),
                  "nguong": has_threshold(text, p["above_threshold"])}
        ok = all(detail.values())
        if "explain_customer" in k:
            rub = explanation_rubric(text, k["explain_customer"])
            detail.update(rub)
            ok = ok and rub["gt_1_yeu_to_dung"] and rub["gt_2_dung_chieu"]
    elif kind == "ho_so":
        prof = k["get_customer"]["profile"]
        wrong, seen = [], 0
        for f in sorted(FEATURES, key=len, reverse=True):
            m = re.search(rf"(?<![A-Za-z]){f}(?![A-Za-z])\W{{0,6}}([^\n|;]{{0,40}})", text)
            if not m:
                continue
            seen += 1
            seg, v = m.group(1), prof.get(f)
            if v is None:
                good = re.search(r"thiếu|không có|trống", seg, re.I) is not None
            elif isinstance(v, (int, float)):
                nums = [x[1] for x in numbers_in(seg)]
                good = bool(nums) and abs(nums[0] - float(v)) < 1e-9
            else:
                good = str(v).lower() in seg.lower()
            if not good:
                wrong.append(f)
        detail = {"so_truong_nhac_den": seen, "truong_sai": wrong, "co_ma": str(case["ma_ho_so"][0]) in text}
        ok = detail["co_ma"] and not wrong and seen >= 1
    elif kind == "thong_ke":
        c = k["count_by_group"]
        if "requested_group" in c:
            g = c["requested_group"]
            detail = {"so_luong": re.search(rf"(?<![\d.,]){g['count']}(?![\d,])", text) is not None, "ty_trong": g["share_display"] in text}
        else:
            detail = {"so_luong": all(re.search(rf"(?<![\d.,]){g['count']}(?![\d,])", text) for g in c["groups"]),
                      "ty_trong": all(g["share_display"] in text for g in c["groups"] if g["count"])}
        ok = all(detail.values())
    elif kind == "danh_sach":
        exp_ids = [x["customer_id"] for x in k["list_customers"]["customers"]]
        got = ids_in(text)
        got = [i for n, i in enumerate(got) if i not in got[:n]]
        detail = {"ma_ky_vong": exp_ids, "ma_trong_phan_hoi": got[:len(exp_ids) + 3], "dung_thu_tu": got[:len(exp_ids)] == exp_ids and len(got) == len(exp_ids)}
        ok = detail["dung_thu_tu"]
    elif kind == "so_sanh":
        ps = k["predict_risk_list"]
        detail = {f"kh_{p['customer_id']}": has_prob(text, p) and str(p["customer_id"]) in text and has_score_anywhere(text, p["score"]) for p in ps}
        ok = all(detail.values())
    elif kind in ("khong_tim_thay", "ma_khong_hop_le"):
        no_prob = not re.search(r"(?<![\d,])0,\d{3,}|\d+,\d%|xác suất\s*(?:là|=)\s*\d", text, re.I)
        if kind == "khong_tim_thay":
            cue = re.search(r"không tìm thấy|không có trong", text, re.I) is not None
        else:   # Bảng 3.18: mã không hợp lệ -> báo không hợp lệ hoặc hỏi lại mã
            cue = re.search(r"không hợp lệ|sai định dạng|kiểm tra lại|nhập lại", text, re.I) is not None or (
                re.search(r"\?|vui lòng|cho mình biết|cung cấp", text, re.I) is not None and re.search(r"mã|CustomerID", text, re.I) is not None)
        detail = {"bao_dung_trang_thai": cue, "khong_neu_xac_suat": no_prob}
        ok = all(detail.values())
    elif kind == "hoi_lai":
        detail = {"khong_goi_cong_cu": not steps, "co_hoi_lai": bool(re.search(r"\?|vui lòng|cho mình biết|cung cấp", text, re.I)) and
                  bool(re.search(r"mã|CustomerID", text, re.I))}
        ok = all(detail.values())
    elif kind == "tu_choi":
        detail = {"tu_choi": re.search(r"không thể|không hỗ trợ|ngoài phạm vi|không đưa ra|không được phép|chỉ hỗ trợ|không thực hiện", text, re.I) is not None,
                  "khong_de_xuat_muc_uu_dai": not re.search(r"(?:giảm|tặng|ưu đãi|voucher)[^\n.]{0,30}\d+\s*(?:%|đ|vnđ|vnd|k\b|nghìn|triệu)", text, re.I)}
        ok = all(detail.values())
    else:
        ok, detail = False, {"loi": f"hanh_vi không xác định: {kind}"}
    return ok, detail


def has_score_anywhere(text, s):
    return has_score(text, s) or re.search(rf"\|\s*{s}\s*(?:/10)?\s*\|", text) is not None


def score_run(case, response):
    text = response.get("output") or ""
    steps = steps_of(response)
    l1 = layer1(case, steps)
    l2_ok, l2 = layer2(case, text, steps)
    fab = fabricated(text, steps, case["cau_hoi"])
    rec_ok = l1["dung_ho_so"] if l1["dung_ho_so"] is not None else True
    passed = l1["dung_cong_cu"] and l1["dung_tham_so"] and rec_ok and l2_ok and not fab and response.get("trang_thai", "ok") == "ok"
    return {**l1, "khop_gia_tri": l2_ok, "chi_tiet": l2, "gia_tri_tu_tao": fab, "so_gia_tri_tu_tao": len(fab), "dat": passed,
            "cong_cu_da_goi": [s["tool"] for s in steps]}
