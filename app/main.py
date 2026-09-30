"""FastAPI 入口：导入 / 重算 / 报告 / 当前工作集接口。"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import RootModel

from . import sample_data, solver, storage
from .validation import validate_payload

app = FastAPI(title="广告播出核销", version="1.0.0")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.on_event("startup")
def _startup() -> None:
    storage.init_db()
    # 首次启动且工作集为空时载入内置示例
    ws = storage.load_workset()
    if not ws["slots"] and not ws["segments"]:
        storage.replace_workset(sample_data.SAMPLE_SLOTS, sample_data.SAMPLE_SEGMENTS)


class ImportPayload(RootModel):
    root: dict


@app.get("/api/state")
def get_state():
    """当前工作集 + 实时分配结果（不落报告）。"""
    ws = storage.load_workset()
    result = solver.allocate(ws["slots"], ws["segments"])
    return {"slots": ws["slots"], "segments": ws["segments"], "result": result}


@app.post("/api/import")
def import_payload(payload: ImportPayload):
    slots, segments, errors = validate_payload(payload.root)
    if errors:
        return JSONResponse(status_code=422, content={"ok": False, "errors": errors})
    storage.replace_workset(slots, segments)
    result = solver.allocate(slots, segments)
    return {"ok": True, "slots": slots, "segments": segments, "result": result}


@app.post("/api/reports")
def create_report():
    """对当前工作集执行全局分配并保存不可变报告（含输入快照与分配证据）。"""
    ws = storage.load_workset()
    result = solver.allocate(ws["slots"], ws["segments"])
    payload = {"input_snapshot": ws, "result": result}
    record = storage.save_report(payload)
    return record


@app.get("/api/reports")
def reports_index():
    return storage.list_reports()


@app.get("/api/reports/{report_id}")
def report_detail(report_id: str):
    report = storage.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在或已被移除")
    return report


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
