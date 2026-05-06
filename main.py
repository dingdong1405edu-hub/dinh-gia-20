"""FastAPI orchestrator for the 3-agent math solver."""
import logging
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from agents.calculator import calculate
from agents.extractor import extract_latex
from agents.renderer import render_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("math-solver")

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

MAX_PDF_BYTES = 10 * 1024 * 1024

app = FastAPI(title="3-Agent Math Solver")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.post("/api/process")
async def process(file: UploadFile = File(...)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf files are accepted")

    contents = await file.read()
    if len(contents) > MAX_PDF_BYTES:
        raise HTTPException(413, f"File too large (max {MAX_PDF_BYTES // 1024 // 1024} MB)")

    job_id = uuid.uuid4().hex[:12]
    pdf_path = UPLOAD_DIR / f"{job_id}.pdf"
    output_path = OUTPUT_DIR / f"{job_id}_result.pdf"
    pdf_path.write_bytes(contents)

    try:
        log.info("[%s] agent1: extracting LaTeX", job_id)
        latex_expr = extract_latex(str(pdf_path))
        log.info("[%s] agent1 done: %s", job_id, latex_expr)

        log.info("[%s] agent2: calculating", job_id)
        calc = calculate(latex_expr)
        log.info("[%s] agent2 done: %s", job_id, calc["result_latex"])

        log.info("[%s] agent3: rendering PDF", job_id)
        render_pdf(
            calc["expression"],
            calc["result_latex"],
            calc["result_numeric"],
            calc.get("steps"),
            str(output_path),
        )
        log.info("[%s] agent3 done", job_id)
    except Exception as exc:
        log.exception("[%s] pipeline failed", job_id)
        raise HTTPException(500, f"Pipeline error: {exc}")
    finally:
        pdf_path.unlink(missing_ok=True)

    return {
        "job_id": job_id,
        "expression": latex_expr,
        "result_latex": calc["result_latex"],
        "result_numeric": calc["result_numeric"],
        "steps": calc.get("steps"),
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
        filename=f"math_result_{job_id}.pdf",
    )


def _safe_job_id(job_id: str) -> bool:
    return job_id.isalnum() and 1 <= len(job_id) <= 32
