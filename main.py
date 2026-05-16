"""FastAPI orchestrator: SME Valuation Report — async pipeline + live progress tracking.

Flow:
  1. Client POST /api/process    → returns job_id immediately, kicks off background task
  2. Client polls /api/status/{job_id} every ~1.5s
  3. State machine per agent: pending → running → done | error
  4. When all agents done → status='done', result included in /api/status response
  5. Errors bubble up with the SPECIFIC agent that failed
"""
import asyncio
import json
import logging
import os
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from agents.analyzer import analyze
from agents.brand_scraper import scrape_brand
from agents.business_profile import analyze_business
from agents.excel_writer import export_excel
from agents.extractor import extract
from agents.industry import analyze_industry
from agents.projector import project
from agents.renderer import SECTIONS, render_all, render_report
from agents.thesis_writer import write as write_thesis
from agents.valuator import value as compute_valuation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sme-valuation")

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_BYTES = 25 * 1024 * 1024

app = FastAPI(title="SME Valuation Report — 8 Agents (Opus 4.7)")


# ============================================================
#   JOB STATE TRACKER (in-memory, single-instance)
# ============================================================
# Mỗi job có state machine cho từng agent:
#   pending → running → done | error
# Client polls /api/status/{job_id} để xem agent nào đang chạy / lỗi.
JOBS: dict[str, dict] = {}

AGENT_NAMES = [
    ("agent1_extract",   "1. Trích xuất BCTC"),
    ("agent_brand",      "Brand Style — Nhận diện màu website"),
    ("agent2_industry",  "2. Phân tích ngành"),
    ("agent4_ratios",    "4. Tỷ số tài chính"),       # song song với agent_brand + agent2
    ("agent3_business",  "3. Tổng quan DN"),
    ("agent5_projector", "5. Dự phóng 5 năm"),
    ("agent6_valuator",  "6. Định giá DCF/Multiples"),
    ("agent7_thesis",    "7. Investment Thesis"),
    ("agent8_renderer",  "8a. Render PDF"),
    ("agent8_excel",     "8b. Xuất Excel"),
    ("agent8_debug",     "8c. Debug PDF + trace"),
]


def _init_job(job_id: str) -> dict:
    return {
        "job_id": job_id,
        "status": "queued",            # queued | running | done | error
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "started_at": None,
        "ended_at": None,
        "total_elapsed_sec": None,
        "current_agent": None,         # agent đang running (cho UI hiển thị)
        "error": None,                 # message nếu status=error
        "error_agent": None,           # agent_id nếu lỗi
        "error_traceback": None,       # full traceback (debug)
        "agents": {
            agent_id: {
                "name": display_name,
                "status": "pending",   # pending | running | done | error
                "started_at": None,
                "elapsed_sec": None,
                "model": None,
                "usage": None,
                "error": None,
            }
            for agent_id, display_name in AGENT_NAMES
        },
        "result": None,                # full output dict khi status=done
    }


def _update_agent(job_id: str, agent_id: str, status: str, **kwargs) -> None:
    """Set agent state. status: 'running' | 'done' | 'error'."""
    if job_id not in JOBS:
        return
    job = JOBS[job_id]
    if agent_id not in job["agents"]:
        return
    job["agents"][agent_id]["status"] = status
    job["agents"][agent_id].update(kwargs)
    if status == "running":
        job["current_agent"] = agent_id
        job["agents"][agent_id]["started_at"] = time.time()
    elif status == "done":
        st = job["agents"][agent_id].get("started_at")
        if st:
            job["agents"][agent_id]["elapsed_sec"] = round(time.time() - st, 2)
        if job["current_agent"] == agent_id:
            job["current_agent"] = None
    elif status == "error":
        st = job["agents"][agent_id].get("started_at")
        if st:
            job["agents"][agent_id]["elapsed_sec"] = round(time.time() - st, 2)
        # global error fields
        job["status"] = "error"
        job["error_agent"] = agent_id
        job["error"] = kwargs.get("error") or "Unknown error"


async def _run_agent(job_id: str, agent_id: str, fn, *args, **kwargs):
    """Wrap an agent call with state tracking + per-agent error capture.

    Returns the result on success. Re-raises (with state set) on error so the
    pipeline orchestrator can stop. The CALLER controls whether we abort or
    continue (rendering uses defensive try/except instead).
    """
    _update_agent(job_id, agent_id, "running")
    log.info("[%s] %s: starting", job_id, agent_id)
    try:
        result = await asyncio.to_thread(fn, *args, **kwargs)
        meta = {}
        if isinstance(result, dict):
            if result.get("model"):
                meta["model"] = result.get("model")
            if result.get("usage"):
                meta["usage"] = result.get("usage")
        _update_agent(job_id, agent_id, "done", **meta)
        elapsed = JOBS[job_id]["agents"][agent_id].get("elapsed_sec")
        log.info("[%s] %s: done in %ss", job_id, agent_id, elapsed)
        return result
    except Exception as exc:
        tb = traceback.format_exc()
        log.exception("[%s] %s: FAILED", job_id, agent_id)
        _update_agent(job_id, agent_id, "error",
                      error=f"{type(exc).__name__}: {exc}",
                      traceback=tb)
        if job_id in JOBS:
            JOBS[job_id]["error_traceback"] = tb
        raise


# ============================================================
#   STATIC PAGES
# ============================================================
@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/agents", response_class=HTMLResponse)
@app.get("/agents.html", response_class=HTMLResponse)
def agents_page() -> str:
    return (BASE_DIR / "static" / "agents.html").read_text(encoding="utf-8")


@app.get("/methodology", response_class=HTMLResponse)
@app.get("/methodology.html", response_class=HTMLResponse)
def methodology_page() -> str:
    return (BASE_DIR / "static" / "methodology.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY"))}


# ============================================================
#   PROCESS (kicks off background pipeline) + STATUS (poll)
# ============================================================
@app.post("/api/process")
async def process(
    file: UploadFile = File(...),
    website: str | None = Form(None),
) -> dict:
    """Validate upload, create job, kick off background pipeline. Returns job_id."""
    name = (file.filename or "").lower()
    suffix = Path(name).suffix
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"Unsupported file type. Allowed: {sorted(ALLOWED_SUFFIXES)}")

    contents = await file.read()
    if len(contents) > MAX_BYTES:
        raise HTTPException(413, f"File too large (max {MAX_BYTES // 1024 // 1024} MB)")

    job_id = uuid.uuid4().hex[:12]
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    upload_path = UPLOAD_DIR / f"{job_id}{suffix}"
    upload_path.write_bytes(contents)

    JOBS[job_id] = _init_job(job_id)

    # Kick off in background — return immediately to client.
    asyncio.create_task(_run_pipeline(job_id, upload_path, job_dir, website or None))

    return {
        "job_id": job_id,
        "status_url": f"/api/status/{job_id}",
    }


@app.get("/api/status/{job_id}")
def get_status(job_id: str) -> dict:
    """Poll endpoint — returns full job state including agent states + result."""
    if not _safe_job_id(job_id):
        raise HTTPException(400, "Invalid job_id")
    job = JOBS.get(job_id)
    if job is None:
        # Có thể server đã restart; nếu file vẫn còn trên disk → coi như done.
        if (OUTPUT_DIR / job_id / "full.pdf").exists():
            return {
                "job_id": job_id,
                "status": "done",
                "note": "(state lost — server restart, but output files still on disk)",
                "files": _file_manifest_from_disk(job_id),
            }
        raise HTTPException(404, f"Job {job_id} not found")
    return job


# ============================================================
#   PIPELINE (background task)
# ============================================================
async def _run_pipeline(job_id: str, upload_path: Path, job_dir: Path,
                        website: str | None = None) -> None:
    """Run the 8-agent pipeline. Updates JOBS[job_id] state continuously."""
    job = JOBS[job_id]
    job["status"] = "running"
    job["started_at"] = time.time()

    full_pdf_path = job_dir / "full.pdf"
    excel_path = job_dir / "data.xlsx"
    debug_pdf_path = job_dir / "debug.pdf"
    trace_path = job_dir / "trace.json"

    trace: dict = {
        "job_id": job_id,
        "created_at": job["created_at"],
        "website": website,
    }

    a1 = a2_industry = a3_business = a4_ratios = None
    a5_projection = a6_valuation = a7_thesis = None
    a8_render = a8_excel = None
    a_brand: dict = {}

    async def _run_brand_safe(company_info: dict) -> dict:
        """Wrap brand scraper: non-fatal — pipeline continues on any failure."""
        try:
            return await _run_agent(
                job_id, "agent_brand", scrape_brand, website, company_info
            )
        except Exception as exc:
            log.warning("[%s] agent_brand failed (non-fatal): %s", job_id, exc)
            return {}

    try:
        # ---- Agent 1: Extract BCTC (sequential, blocks all downstream).
        a1 = await _run_agent(job_id, "agent1_extract", extract, str(upload_path))
        trace["agent1_extract"] = a1
        financials = (a1 or {}).get("financials") or {}
        if not financials:
            raise RuntimeError("Không trích xuất được dữ liệu tài chính từ BCTC.")

        company_info = financials.get("company") or {}

        # ---- Agents Brand + 2 + 4 in parallel (brand is non-fatal).
        a_brand, a2_industry, a4_ratios = await asyncio.gather(
            _run_brand_safe(company_info),
            _run_agent(job_id, "agent2_industry", analyze_industry, financials),
            _run_agent(job_id, "agent4_ratios", analyze, financials),
        )
        trace["agent_brand"] = a_brand
        trace["agent2_industry"] = a2_industry
        trace["agent4_ratios"] = a4_ratios

        # ---- Agent 3: business (needs industry).
        a3_business = await _run_agent(
            job_id, "agent3_business", analyze_business,
            financials, a2_industry.get("industry") or {},
        )
        trace["agent3_business"] = a3_business

        # ---- Agent 5: projector.
        a5_projection = await _run_agent(
            job_id, "agent5_projector", project,
            financials, a4_ratios, a2_industry.get("industry") or {},
        )
        trace["agent5_projector"] = a5_projection

        # ---- Agent 6: valuator.
        a6_valuation = await _run_agent(
            job_id, "agent6_valuator", compute_valuation,
            financials, a4_ratios, a2_industry.get("industry") or {}, a5_projection,
        )
        trace["agent6_valuator"] = a6_valuation

        # ---- Agent 7: thesis writer.
        a7_thesis = await _run_agent(
            job_id, "agent7_thesis", write_thesis,
            financials, a4_ratios,
            a2_industry.get("industry") or {},
            a3_business.get("business") or {},
            a5_projection, a6_valuation,
        )
        trace["agent7_thesis"] = a7_thesis

        # ---- Agent 8a: render PDFs (pass brand_style if scraper succeeded).
        brand_style = (a_brand or {}).get("style_override") or None
        payload = {
            "extracted": a1,
            "industry": a2_industry,
            "business": a3_business,
            "ratios": a4_ratios,
            "projection": a5_projection,
            "valuation": a6_valuation,
            "thesis": a7_thesis,
        }
        a8_render = await _run_agent(
            job_id, "agent8_renderer", render_all,
            payload, str(job_dir), str(full_pdf_path),
            brand_style,
        )
        trace["agent8_renderer"] = a8_render

        # ---- Agent 8b: Excel — DEFENSIVE (don't crash pipeline if fails).
        _update_agent(job_id, "agent8_excel", "running")
        try:
            a8_excel = await asyncio.to_thread(export_excel, payload, str(excel_path))
            trace["agent8_excel"] = a8_excel
            _update_agent(job_id, "agent8_excel", "done")
        except Exception as exc:
            log.exception("[%s] agent8_excel failed (non-fatal)", job_id)
            a8_excel = {"error": repr(exc), "sheets": []}
            trace["agent8_excel"] = a8_excel
            _update_agent(job_id, "agent8_excel", "error",
                          error=f"{type(exc).__name__}: {exc}")

    except Exception as exc:
        # Agent đã được mark "error" trong _run_agent.
        # Còn nếu lỗi ở chỗ khác (vd RuntimeError "không trích xuất được"), set global.
        if job["status"] != "error":
            job["status"] = "error"
            job["error"] = f"{type(exc).__name__}: {exc}"
            job["error_traceback"] = traceback.format_exc()
        upload_path.unlink(missing_ok=True)
        job["ended_at"] = time.time()
        if job["started_at"]:
            job["total_elapsed_sec"] = round(job["ended_at"] - job["started_at"], 2)
        return

    job["total_elapsed_sec"] = round(time.time() - job["started_at"], 2)
    trace["total_elapsed_sec"] = job["total_elapsed_sec"]

    # ---- Trace + debug PDF (best-effort, không cản trở response).
    _update_agent(job_id, "agent8_debug", "running")
    try:
        trace_path.write_text(
            json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        log.exception("[%s] failed to write trace.json", job_id)

    try:
        await asyncio.to_thread(render_report, trace, str(debug_pdf_path))
        _update_agent(job_id, "agent8_debug", "done")
    except Exception as exc:
        log.exception("[%s] failed to render debug PDF", job_id)
        _update_agent(job_id, "agent8_debug", "error",
                      error=f"{type(exc).__name__}: {exc}")

    upload_path.unlink(missing_ok=True)

    # ---- Build final response.
    industry_data = (a2_industry or {}).get("industry") or {}
    business_data = (a3_business or {}).get("business") or {}
    valuation_summary = (a6_valuation or {}).get("summary") or {}
    thesis_data = (a7_thesis or {}).get("thesis") or {}

    job["result"] = {
        "job_id": job_id,
        "company": (a1.get("financials") or {}).get("company") or {} if a1 else {},
        "period": (a1.get("financials") or {}).get("period") or {} if a1 else {},
        "unit": (a1.get("financials") or {}).get("unit") if a1 else None,
        "industry_name": industry_data.get("industry_name"),
        "growth_stage": business_data.get("growth_stage"),
        "competitive_position": business_data.get("competitive_position"),
        "executive_summary": thesis_data.get("executive_summary"),
        "valuation_summary": valuation_summary,
        "ratios": (a4_ratios or {}).get("ratios"),
        "growth": (a4_ratios or {}).get("growth"),
        "investment_thesis": thesis_data.get("investment_thesis"),
        "deal_recommendation": thesis_data.get("deal_recommendation"),
        "files": _file_manifest(job_id, a8_render or {}, a8_excel or {}),
        "brand": {
            "url_used":    (a_brand or {}).get("url_used"),
            "url_source":  (a_brand or {}).get("url_source"),
            "brand_colors": (a_brand or {}).get("brand_colors"),
            "notes":       (a_brand or {}).get("notes"),
            "elapsed_sec": (a_brand or {}).get("elapsed_sec"),
        },
        "meta": {
            "agent_brand":    _meta(a_brand),
            "agent1_extract": _meta(a1),
            "agent2_industry": _meta(a2_industry),
            "agent3_business": _meta(a3_business),
            "agent4_ratios": _meta(a4_ratios),
            "agent5_projector": _meta(a5_projection),
            "agent6_valuator": _meta(a6_valuation),
            "agent7_thesis": _meta(a7_thesis),
            "agent8_renderer": {
                "elapsed_sec": (a8_render or {}).get("elapsed_sec"),
                "total_pages": (a8_render or {}).get("total_pages"),
                "sections": len((a8_render or {}).get("section_files") or []),
            },
            "agent8_excel": {
                "elapsed_sec": (a8_excel or {}).get("elapsed_sec"),
                "size_bytes": (a8_excel or {}).get("size_bytes"),
                "sheets": (a8_excel or {}).get("sheets") or [],
            },
            "total_elapsed_sec": job["total_elapsed_sec"],
        },
    }
    job["status"] = "done"
    job["ended_at"] = time.time()


# ============================================================
#   FILE MANIFEST + DOWNLOADS
# ============================================================
def _file_manifest(job_id: str, render_meta: dict, excel_meta: dict) -> list[dict]:
    """List output files for the UI. Stat() each so we never link to a non-existent file."""
    items = []
    job_dir = OUTPUT_DIR / job_id

    full_pdf = job_dir / "full.pdf"
    if full_pdf.exists():
        items.append({
            "kind": "full",
            "title": "Báo cáo đầy đủ (toàn bộ 12 mục)",
            "category": "pdf_full",
            "format": "PDF",
            "pages": render_meta.get("total_pages") or 0,
            "size_bytes": full_pdf.stat().st_size,
            "url": f"/api/download/{job_id}/full",
        })

    for f in render_meta.get("section_files") or []:
        section_path = job_dir / f.get("file_name", "")
        if not section_path.exists():
            continue
        items.append({
            "kind": f["kind"],
            "title": f["title"],
            "category": "pdf_section",
            "format": "PDF",
            "pages": f["pages"],
            "size_bytes": section_path.stat().st_size,
            "url": f"/api/download/{job_id}/section/{f['kind']}",
        })

    excel_path = job_dir / "data.xlsx"
    if excel_path.exists():
        sheet_count = len(excel_meta.get("sheets") or [])
        items.append({
            "kind": "excel",
            "title": f"Dữ liệu tài chính ({sheet_count} sheet)" if sheet_count else "Dữ liệu tài chính",
            "category": "excel",
            "format": "XLSX",
            "pages": None,
            "size_bytes": excel_path.stat().st_size,
            "url": f"/api/download/{job_id}/excel",
        })

    debug_path = job_dir / "debug.pdf"
    if debug_path.exists():
        items.append({
            "kind": "debug",
            "title": "Debug PDF (trace mọi agent)",
            "category": "debug",
            "format": "PDF",
            "pages": None,
            "size_bytes": debug_path.stat().st_size,
            "url": f"/api/download/{job_id}/debug",
        })
    trace_path = job_dir / "trace.json"
    if trace_path.exists():
        items.append({
            "kind": "trace",
            "title": "Trace JSON",
            "category": "debug",
            "format": "JSON",
            "pages": None,
            "size_bytes": trace_path.stat().st_size,
            "url": f"/api/download/{job_id}/trace",
        })
    return items


def _file_manifest_from_disk(job_id: str) -> list[dict]:
    """Recover-mode: server restart → JOBS state lost. Build manifest by walking disk."""
    job_dir = OUTPUT_DIR / job_id
    if not job_dir.is_dir():
        return []
    items = []
    for f in sorted(job_dir.iterdir()):
        if not f.is_file():
            continue
        items.append({
            "kind": f.stem,
            "title": f.name,
            "category": "pdf_full" if f.name == "full.pdf" else "pdf_section" if f.suffix == ".pdf" else "excel" if f.suffix == ".xlsx" else "debug",
            "format": f.suffix.lstrip(".").upper(),
            "pages": None,
            "size_bytes": f.stat().st_size,
            "url": f"/api/download/{job_id}/file/{f.name}",
        })
    return items


def _meta(payload):
    if not isinstance(payload, dict):
        return {}
    return {
        "model": payload.get("model"),
        "elapsed_sec": payload.get("elapsed_sec"),
        "usage": payload.get("usage"),
    }


_SECTION_KINDS = {kind for kind, _slug, _title, _builder in SECTIONS}
_SECTION_SLUG_BY_KIND = {kind: slug for kind, slug, _t, _b in SECTIONS}


@app.get("/api/files/{job_id}")
def list_files(job_id: str) -> dict:
    if not _safe_job_id(job_id):
        raise HTTPException(400, "Invalid job_id")
    job_dir = OUTPUT_DIR / job_id
    if not job_dir.is_dir():
        raise HTTPException(404, f"Job {job_id} not found")
    files = []
    for f in sorted(job_dir.iterdir()):
        if not f.is_file():
            continue
        files.append({
            "name": f.name,
            "size_bytes": f.stat().st_size,
            "url": f"/api/download/{job_id}/file/{f.name}",
        })
    return {"job_id": job_id, "files": files}


@app.get("/api/download/{job_id}/section/{kind}")
def download_section(job_id: str, kind: str) -> FileResponse:
    if not _safe_job_id(job_id):
        raise HTTPException(400, "Invalid job_id")
    if kind not in _SECTION_KINDS:
        raise HTTPException(400, f"Invalid section kind. Use one of: {sorted(_SECTION_KINDS)}")
    slug = _SECTION_SLUG_BY_KIND[kind]
    fpath = OUTPUT_DIR / job_id / f"{slug}.pdf"
    if not fpath.exists():
        raise HTTPException(404, f"Section {kind} not found for job {job_id}")
    return FileResponse(
        fpath,
        media_type="application/pdf",
        filename=f"{slug}_{job_id}.pdf",
    )


@app.get("/api/download/{job_id}/file/{name}")
def download_file_by_name(job_id: str, name: str) -> FileResponse:
    if not _safe_job_id(job_id):
        raise HTTPException(400, "Invalid job_id")
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "Invalid file name")
    fpath = OUTPUT_DIR / job_id / name
    if not fpath.is_file():
        raise HTTPException(404, "File not found")
    media = "application/pdf" if name.endswith(".pdf") else (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if name.endswith(".xlsx") else
        "application/json" if name.endswith(".json") else "application/octet-stream"
    )
    return FileResponse(fpath, media_type=media, filename=name)


@app.get("/api/download/{job_id}/{kind}")
def download(job_id: str, kind: str) -> FileResponse:
    if not _safe_job_id(job_id):
        raise HTTPException(400, "Invalid job_id")
    job_dir = OUTPUT_DIR / job_id
    mapping = {
        "full":      ("full.pdf",  "application/pdf",  f"dinh_gia_{job_id}.pdf"),
        "valuation": ("full.pdf",  "application/pdf",  f"dinh_gia_{job_id}.pdf"),
        "excel":     ("data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      f"data_{job_id}.xlsx"),
        "debug":     ("debug.pdf", "application/pdf",  f"debug_{job_id}.pdf"),
        "trace":     ("trace.json","application/json", f"trace_{job_id}.json"),
    }
    if kind not in mapping:
        raise HTTPException(400, "Invalid kind. Use: full | excel | debug | trace | section/<kind>")
    fname, mime, dl_name = mapping[kind]
    fpath = job_dir / fname
    if not fpath.exists():
        raise HTTPException(404, f"{kind} not found for job {job_id}")
    return FileResponse(fpath, media_type=mime, filename=dl_name)


def _safe_job_id(job_id: str) -> bool:
    return job_id.isalnum() and 1 <= len(job_id) <= 32
