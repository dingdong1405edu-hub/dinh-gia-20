"""FastAPI orchestrator: worksheet -> answers PDF + debug report + trace.json."""
import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from agents.calculator import solve
from agents.extractor import extract
from agents.renderer import render_answers, render_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("math-solver")

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_BYTES = 15 * 1024 * 1024

app = FastAPI(title="Worksheet Solver — 3 Agents (Opus 4.7 + thinking)")


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
    answers_path = OUTPUT_DIR / f"{job_id}_answers.pdf"
    report_path = OUTPUT_DIR / f"{job_id}_report.pdf"
    trace_path = OUTPUT_DIR / f"{job_id}_trace.json"
    upload_path.write_bytes(contents)

    pipeline_start = time.time()
    trace: dict = {
        "job_id": job_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        log.info("[%s] agent1: extract", job_id)
        a1 = extract(str(upload_path))
        trace["agent1"] = a1
        log.info("[%s] agent1 done: %d problems in %.2fs",
                 job_id, len(a1["problems"]), a1["elapsed_sec"])
        if not a1["problems"]:
            raise HTTPException(422, "Không tìm thấy bài tập nào trong file. Hãy thử ảnh/PDF rõ hơn.")

        log.info("[%s] agent2: solve", job_id)
        a2 = solve(a1["problems"])
        trace["agent2"] = a2
        log.info("[%s] agent2 done: %d solutions in %.2fs",
                 job_id, len(a2["solutions"]), a2["elapsed_sec"])

        log.info("[%s] agent3: render answers", job_id)
        a3 = render_answers(a1["problems"], a2["solutions"], str(answers_path))
        trace["agent3"] = a3
        log.info("[%s] agent3 done: %d pages in %.2fs",
                 job_id, a3["pages"], a3["elapsed_sec"])
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

    return {
        "job_id": job_id,
        "count": len(trace["agent1"]["problems"]),
        "problems": trace["agent1"]["problems"],
        "solutions": trace["agent2"]["solutions"],
        "transcription": trace["agent1"].get("transcription", ""),
        "thinking": {
            "agent1": trace["agent1"].get("thinking", ""),
            "agent2": trace["agent2"].get("thinking", ""),
        },
        "raw_response": {
            "agent1": trace["agent1"].get("raw_response", ""),
            "agent2": trace["agent2"].get("raw_response", ""),
        },
        "meta": {
            "agent1": {
                "model": trace["agent1"].get("model"),
                "elapsed_sec": trace["agent1"].get("elapsed_sec"),
                "usage": trace["agent1"].get("usage"),
            },
            "agent2": {
                "model": trace["agent2"].get("model"),
                "elapsed_sec": trace["agent2"].get("elapsed_sec"),
                "usage": trace["agent2"].get("usage"),
            },
            "agent3": {
                "elapsed_sec": trace["agent3"].get("elapsed_sec"),
                "pages": trace["agent3"].get("pages"),
            },
            "total_elapsed_sec": trace["total_elapsed_sec"],
        },
        "answers_url": f"/api/download/{job_id}/answers",
        "report_url": f"/api/download/{job_id}/report",
        "trace_url": f"/api/download/{job_id}/trace",
    }


@app.get("/api/download/{job_id}/{kind}")
def download(job_id: str, kind: str) -> FileResponse:
    if not _safe_job_id(job_id):
        raise HTTPException(400, "Invalid job_id")

    mapping = {
        "answers": (f"{job_id}_answers.pdf", "application/pdf", f"dap_an_{job_id}.pdf"),
        "report": (f"{job_id}_report.pdf", "application/pdf", f"bao_cao_debug_{job_id}.pdf"),
        "trace": (f"{job_id}_trace.json", "application/json", f"trace_{job_id}.json"),
    }
    if kind not in mapping:
        raise HTTPException(400, "Invalid kind. Use: answers | report | trace")

    fname, mime, dl_name = mapping[kind]
    fpath = OUTPUT_DIR / fname
    if not fpath.exists():
        raise HTTPException(404, f"{kind} not found for job {job_id}")
    return FileResponse(fpath, media_type=mime, filename=dl_name)


def _safe_job_id(job_id: str) -> bool:
    return job_id.isalnum() and 1 <= len(job_id) <= 32
