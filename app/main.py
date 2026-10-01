"""FastAPI 入口：广告播出核销 Web 应用。"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.schemas import validate_dataset
from app.solver import solve
from app.store import Store

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = os.environ.get("APP_DB_PATH", str(BASE_DIR / "data" / "reports.db"))

app = FastAPI(title="广告播出核销", version="1.0.0")
store = Store(DB_PATH)

SAMPLE = {
    "channel": "示例频道 CH-01",
    "slots": [
        {"id": "S1", "material_id": "M-A", "planned_start": 1000,
         "duration": 1000, "tolerance": 200, "max_gap": 50},
        {"id": "S2", "material_id": "M-A", "planned_start": 3000,
         "duration": 800, "tolerance": 100, "max_gap": 0},
        {"id": "S3", "material_id": "M-B", "planned_start": 2000,
         "duration": 600, "tolerance": 300, "max_gap": 100},
        {"id": "S4", "material_id": "M-C", "planned_start": 5000,
         "duration": 500, "tolerance": 50, "max_gap": 0},
    ],
    "fragments": [
        # M-A 可拼出 S1（两段，停顿 40ms）
        {"id": "F01", "material_id": "M-A", "on_air_start": 950,
         "on_air_end": 1450, "source_start": 0, "source_end": 500},
        {"id": "F02", "material_id": "M-A", "on_air_start": 1490,
         "on_air_end": 1990, "source_start": 500, "source_end": 1000},
        # M-A 为 S2 准备的片段（与上面交错在时间轴上）
        {"id": "F03", "material_id": "M-A", "on_air_start": 3000,
         "on_air_end": 3400, "source_start": 0, "source_end": 400},
        {"id": "F04", "material_id": "M-A", "on_air_start": 3400,
         "on_air_end": 3800, "source_start": 400, "source_end": 800},
        # M-B：S3 只有 400ms 素材，无法拼满 600ms
        {"id": "F05", "material_id": "M-B", "on_air_start": 2100,
         "on_air_end": 2500, "source_start": 0, "source_end": 400},
        # M-A 多余片段（与 S1 首片段同源区间，竞争/闲置）
        {"id": "F06", "material_id": "M-A", "on_air_start": 1000,
         "on_air_end": 1500, "source_start": 0, "source_end": 500},
        # 完全无关的闲置片段
        {"id": "F07", "material_id": "M-Z", "on_air_start": 6000,
         "on_air_end": 6300, "source_start": 100, "source_end": 400},
    ],
}


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/sample")
def sample() -> dict:
    return SAMPLE


@app.post("/api/verify")
def verify(payload: dict) -> JSONResponse:
    dataset, errors = validate_dataset(payload)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    result = solve(dataset)
    meta = store.save_report(dataset, result)
    return JSONResponse(
        {
            "report_id": meta["report_id"],
            "created_at": meta["created_at"],
            "input": dataset,
            "result": result,
        }
    )


@app.get("/api/reports")
def reports() -> dict:
    return {"reports": store.list_reports()}


@app.get("/api/reports/{report_id}")
def report_detail(report_id: str) -> dict:
    report = store.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return report


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
