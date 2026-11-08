"""Dịch vụ dự đoán (FastAPI) cho nguyên mẫu AI Agent: chỉ đọc, có kiểm tra tham số và khóa truy cập.

Chạy cục bộ:  SERVICE_API_KEY=... uvicorn app:app --port 7860
Mọi công cụ: POST /tools/<ten_cong_cu> với thân JSON; header X-API-Key.
"""
import hmac
import json
import logging
import os
import sys
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core import ChurnService, ServiceError

logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")
log = logging.getLogger("dich_vu_du_doan")

service = ChurnService()
app = FastAPI(title="Dịch vụ dự đoán nguy cơ rời bỏ (KLTN)", version=service.service_version,
              docs_url=None, redoc_url=None, openapi_url=None)


def _authorized(request: Request):
    key = os.environ.get("SERVICE_API_KEY", "")
    if not key:
        return False, JSONResponse({"status": "service_error", "message": "Dịch vụ chưa được cấu hình SERVICE_API_KEY."}, status_code=503)
    given = request.headers.get("x-api-key", "")
    if not hmac.compare_digest(given.encode(), key.encode()):
        return False, JSONResponse({"status": "unauthorized", "message": "Thiếu hoặc sai X-API-Key."}, status_code=401)
    return True, None


def _log(**fields):
    log.info(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **fields}, ensure_ascii=False, default=str))


@app.get("/health")
def health():
    return {"status": "ok", "service_version": service.service_version, "model_version": service.model_version,
            "crm_records": int(len(service.crm)), "shap_version": service.shap_version}


@app.post("/tools/{tool}")
async def tool(tool: str, request: Request):
    ok, resp = _authorized(request)
    if not ok:
        _log(event="tool_call", tool=tool, status="unauthorized")
        return resp
    t0 = time.perf_counter()
    try:
        params = await request.json()
    except Exception:
        params = {}
    if not isinstance(params, dict):
        params = {}
    allowed = {"customer_id", "top_k", "risk_group", "filters", "limit"}
    params = {k: v for k, v in params.items() if k in allowed}
    try:
        out = service.call(tool, params)
        code = 200
    except ServiceError as e:
        out, code = {"status": "service_error", "tool": tool, "message": str(e)}, 500
    except Exception as e:  # lỗi dữ liệu đầu vào của pipeline (sai kiểu, giá trị âm...)
        out, code = {"status": "validation_error", "tool": tool, "message": f"Không thể dự đoán: {e}"}, 200
    _log(event="tool_call", tool=tool, params=params, status=out.get("status"),
         duration_ms=round(1000 * (time.perf_counter() - t0), 1), model_version=service.model_version)
    return JSONResponse(out, status_code=code)


@app.get("/eval/score_table")
def score_table(request: Request):
    """Chỉ phục vụ tạo bộ tình huống kiểm thử (mục 3.11.1); Agent không có công cụ gọi điểm cuối này."""
    ok, resp = _authorized(request)
    if not ok:
        return resp
    _log(event="score_table")
    return {"status": "ok", "model_version": service.model_version, "rows": service.score_table()}
