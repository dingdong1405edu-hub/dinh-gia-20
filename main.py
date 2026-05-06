"""FastAPI orchestrator: worksheet -> answers PDF."""
import logging
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from agents.calculator import solve_problems
from agents.extractor import extract_problems
from agents.renderer import render_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("math-solver")

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_BYTES = 15 * 1024 * 1024

app = FastAPI(title="Worksheet Solver — 3 Agents")


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
    output_path = OUTPUT_DIR / f"{job_id}_result.pdf"
    upload_path.write_bytes(contents)

    try:
        log.info("[%s] agent1: extracting problems from %s", job_id, suffix)
        problems = extract_problems(str(upload_path))
        log.info("[%s] agent1 done: %d problems", job_id, len(problems))
        if not problems:
            raise HTTPException(422, "Không tìm thấy bài tập nào trong file. Hãy thử ảnh/PDF rõ hơn.")

        log.info("[%s] agent2: solving %d problems", job_id, len(problems))
        solutions = solve_problems(problems)
        log.info("[%s] agent2 done: %d solutions", job_id, len(solutions))

        log.info("[%s] agent3: rendering PDF", job_id)
        render_pdf(problems, solutions, str(output_path))
        log.info("[%s] agent3 done -> %s", job_id, output_path)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("[%s] pipeline failed", job_id)
        raise HTTPException(500, f"Pipeline error: {exc}")
    finally:
        upload_path.unlink(missing_ok=True)

    return {
        "job_id": job_id,
        "count": len(problems),
        "problems": problems,
        "solutions": solutions,
        "download_url": f"/api/download/{job_id}",
    }


@app.get("/api/download/{job_id}")
def download(job_id: str) -> FileResponse:
    if not _safe_job_id(job_id):
        raise HTTPException(400, "Invalid job_id")
    output_path = OUTPUT_DIR / f"{job_id}_result.pdf"
    if not output_path.exists():
        raise HTTPException(404, "Result not found")
    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename=f"dap_an_{job_id}.pdf",
    )


def _safe_job_id(job_id: str) -> bool:
    return job_id.isalnum() and 1 <= len(job_id) <= 32
