"""FastAPI orchestrator: financial report -> analysis PDF + debug report + trace.json."""
import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from agents.analyzer import analyze
from agents.extractor import extract
from agents.renderer import render_analysis, render_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("financial-analyzer")

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_BYTES = 20 * 1024 * 1024

app = FastAPI(title="Financial Report Analyzer — 3 Agents (Opus 4.7)")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.post("/api/process")
async def process(file: UploadFile = File(...)) -> dict:
    name = (file.filename or "").lower()
    suffix = Path(name).suffix
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"Unsupported file type. Allowed: {sorted(ALLOWED_SUFFIXES)}")

    contents = await file.read()
    if len(contents) > MAX_BYTES:
        raise HTTPException(413, f"File too large (max {MAX_BYTES // 1024 // 1024} MB)")

    job_id = uuid.uuid4().hex[:12]
    upload_path = UPLOAD_DIR / f"{job_id}{suffix}"
    analysis_path = OUTPUT_DIR / f"{job_id}_analysis.pdf"
    report_path = OUTPUT_DIR / f"{job_id}_report.pdf"
    trace_path = OUTPUT_DIR / f"{job_id}_trace.json"
    upload_path.write_bytes(contents)

    pipeline_start = time.time()
    trace: dict = {
        "job_id": job_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        log.info("[%s] agent1: extract financials", job_id)
        a1 = extract(str(upload_path))
        trace["agent1"] = a1
        log.info("[%s] agent1 done in %.2fs", job_id, a1["elapsed_sec"])
        if not a1.get("financials"):
            raise HTTPException(422, "Không trích xuất được dữ liệu tài chính từ file. Hãy thử file rõ hơn.")

        log.info("[%s] agent2: compute ratios + analyze", job_id)
        a2 = analyze(a1)
        trace["agent2"] = a2
        log.info("[%s] agent2 done in %.2fs", job_id, a2["elapsed_sec"])

        log.info("[%s] agent3: render analysis PDF", job_id)
        a3 = render_analysis(a1, a2, str(analysis_path))
        trace["agent3"] = a3
        log.info("[%s] agent3 done: %d pages in %.2fs", job_id, a3["pages"], a3["elapsed_sec"])
    except HTTPException:
        upload_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        log.exception("[%s] pipeline failed", job_id)
        upload_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Pipeline error: {exc}")

    trace["total_elapsed_sec"] = round(time.time() - pipeline_start, 2)

    try:
        trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        log.exception("[%s] failed to write trace.json", job_id)

    try:
        report_meta = render_report(trace, str(report_path))
        log.info("[%s] report rendered: %d pages", job_id, report_meta["pages"])
    except Exception:
        log.exception("[%s] failed to render report", job_id)

    upload_path.unlink(missing_ok=True)

    financials = a1.get("financials") or {}
    insights = a2.get("insights") or {}

    return {
        "job_id": job_id,
        "company": financials.get("company") or {},
        "period": financials.get("period") or {},
        "currency": financials.get("currency"),
        "unit": financials.get("unit"),
        "health_score": insights.get("health_score"),
        "health_grade": insights.get("health_grade"),
        "executive_summary": insights.get("executive_summary"),
        "key_insights": insights.get("key_insights") or [],
        "strengths": insights.get("strengths") or [],
        "weaknesses": insights.get("weaknesses") or [],
        "red_flags": insights.get("red_flags") or [],
        "trends": insights.get("trends") or [],
        "recommendations": insights.get("recommendations") or [],
        "ratios": a2.get("ratios") or {},
        "raw_transcription": (financials.get("raw_transcription") or "")[:8000],
        "thinking": {
            "agent1": a1.get("thinking", ""),
            "agent2": a2.get("thinking", ""),
        },
        "raw_response": {
            "agent1": a1.get("raw_response", ""),
            "agent2": a2.get("raw_response", ""),
        },
        "meta": {
            "agent1": {
                "model": a1.get("model"),
                "elapsed_sec": a1.get("elapsed_sec"),
                "usage": a1.get("usage"),
            },
            "agent2": {
                "model": a2.get("model"),
                "elapsed_sec": a2.get("elapsed_sec"),
                "usage": a2.get("usage"),
            },
            "agent3": {
                "elapsed_sec": a3.get("elapsed_sec"),
                "pages": a3.get("pages"),
            },
            "total_elapsed_sec": trace["total_elapsed_sec"],
        },
        "analysis_url": f"/api/download/{job_id}/analysis",
        "report_url": f"/api/download/{job_id}/report",
        "trace_url": f"/api/download/{job_id}/trace",
    }


@app.get("/api/download/{job_id}/{kind}")
def download(job_id: str, kind: str) -> FileResponse:
    if not _safe_job_id(job_id):
        raise HTTPException(400, "Invalid job_id")

    mapping = {
        "analysis": (f"{job_id}_analysis.pdf", "application/pdf", f"phan_tich_BCTC_{job_id}.pdf"),
        "report": (f"{job_id}_report.pdf", "application/pdf", f"bao_cao_debug_{job_id}.pdf"),
        "trace": (f"{job_id}_trace.json", "application/json", f"trace_{job_id}.json"),
    }
    if kind not in mapping:
        raise HTTPException(400, "Invalid kind. Use: analysis | report | trace")

    fname, mime, dl_name = mapping[kind]
    fpath = OUTPUT_DIR / fname
    if not fpath.exists():
        raise HTTPException(404, f"{kind} not found for job {job_id}")
    return FileResponse(fpath, media_type=mime, filename=dl_name)


def _safe_job_id(job_id: str) -> bool:
    return job_id.isalnum() and 1 <= len(job_id) <= 32
