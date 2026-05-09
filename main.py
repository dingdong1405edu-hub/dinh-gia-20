"""FastAPI orchestrator: SME Valuation Report — 7 agents + render (PDF per section + Excel)."""
import asyncio
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

app = FastAPI(title="SME Valuation Report — 7 Agents (Opus 4.7)")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/agents", response_class=HTMLResponse)
@app.get("/agents.html", response_class=HTMLResponse)
def agents_page() -> str:
    return (BASE_DIR / "static" / "agents.html").read_text(encoding="utf-8")


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
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    upload_path = UPLOAD_DIR / f"{job_id}{suffix}"
    full_pdf_path = job_dir / "full.pdf"
    excel_path = job_dir / "data.xlsx"
    debug_pdf_path = job_dir / "debug.pdf"
    trace_path = job_dir / "trace.json"
    upload_path.write_bytes(contents)

    pipeline_start = time.time()
    trace: dict = {
        "job_id": job_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        # ---- Agent 1
        log.info("[%s] agent1: extracting financials", job_id)
        a1 = await asyncio.to_thread(extract, str(upload_path))
        trace["agent1_extract"] = a1
        financials = a1.get("financials") or {}
        if not financials:
            raise HTTPException(422, "Không trích xuất được dữ liệu tài chính.")

        # ---- Agents 2 + 4 in parallel
        log.info("[%s] agents 2+4 in parallel", job_id)
        a2_industry, a4_ratios = await asyncio.gather(
            asyncio.to_thread(analyze_industry, financials),
            asyncio.to_thread(analyze, financials),
        )
        trace["agent2_industry"] = a2_industry
        trace["agent4_ratios"] = a4_ratios

        # ---- Agent 3
        log.info("[%s] agent3: business profile", job_id)
        a3_business = await asyncio.to_thread(
            analyze_business, financials, a2_industry.get("industry") or {}
        )
        trace["agent3_business"] = a3_business

        # ---- Agent 5
        log.info("[%s] agent5: projecting 5y", job_id)
        a5_projection = await asyncio.to_thread(
            project, financials, a4_ratios, a2_industry.get("industry") or {}
        )
        trace["agent5_projector"] = a5_projection

        # ---- Agent 6
        log.info("[%s] agent6: valuation", job_id)
        a6_valuation = await asyncio.to_thread(
            compute_valuation, financials, a4_ratios,
            a2_industry.get("industry") or {}, a5_projection,
        )
        trace["agent6_valuator"] = a6_valuation

        # ---- Agent 7
        log.info("[%s] agent7: thesis", job_id)
        a7_thesis = await asyncio.to_thread(
            write_thesis,
            financials, a4_ratios,
            a2_industry.get("industry") or {},
            a3_business.get("business") or {},
            a5_projection,
            a6_valuation,
        )
        trace["agent7_thesis"] = a7_thesis

        # ---- Agent 8a: render full PDF + per-section PDFs
        log.info("[%s] agent8a: rendering PDFs (full + per section)", job_id)
        payload = {
            "extracted": a1,
            "industry": a2_industry,
            "business": a3_business,
            "ratios": a4_ratios,
            "projection": a5_projection,
            "valuation": a6_valuation,
            "thesis": a7_thesis,
        }
        a8_render = await asyncio.to_thread(
            render_all, payload, str(job_dir), str(full_pdf_path)
        )
        trace["agent8_renderer"] = a8_render
        log.info("[%s] agent8a done: %d pages, %d sections",
                 job_id, a8_render["total_pages"], len(a8_render["section_files"]))

        # ---- Agent 8b: Excel
        log.info("[%s] agent8b: rendering Excel", job_id)
        a8_excel = await asyncio.to_thread(export_excel, payload, str(excel_path))
        trace["agent8_excel"] = a8_excel
        log.info("[%s] agent8b done: %s sheets", job_id, len(a8_excel.get("sheets") or []))

    except HTTPException:
        upload_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        log.exception("[%s] pipeline failed", job_id)
        upload_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Pipeline error: {exc}")

    trace["total_elapsed_sec"] = round(time.time() - pipeline_start, 2)

    try:
        trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception:
        log.exception("[%s] failed to write trace.json", job_id)

    try:
        debug_meta = render_report(trace, str(debug_pdf_path))
        log.info("[%s] debug report rendered: %d pages", job_id, debug_meta["pages"])
    except Exception:
        log.exception("[%s] failed to render debug report", job_id)

    upload_path.unlink(missing_ok=True)

    industry_data = (a2_industry or {}).get("industry") or {}
    business_data = (a3_business or {}).get("business") or {}
    valuation_summary = (a6_valuation or {}).get("summary") or {}
    thesis_data = (a7_thesis or {}).get("thesis") or {}

    return {
        "job_id": job_id,
        "company": financials.get("company") or {},
        "period": financials.get("period") or {},
        "unit": financials.get("unit"),
        "industry_name": industry_data.get("industry_name"),
        "growth_stage": business_data.get("growth_stage"),
        "competitive_position": business_data.get("competitive_position"),
        "executive_summary": thesis_data.get("executive_summary"),
        "valuation_summary": valuation_summary,
        "ratios": (a4_ratios or {}).get("ratios"),
        "growth": (a4_ratios or {}).get("growth"),
        "investment_thesis": thesis_data.get("investment_thesis"),
        "deal_recommendation": thesis_data.get("deal_recommendation"),
        "files": _file_manifest(job_id, a8_render, a8_excel),
        "meta": {
            "agent1_extract": _meta(a1),
            "agent2_industry": _meta(a2_industry),
            "agent3_business": _meta(a3_business),
            "agent4_ratios": _meta(a4_ratios),
            "agent5_projector": _meta(a5_projection),
            "agent6_valuator": _meta(a6_valuation),
            "agent7_thesis": _meta(a7_thesis),
            "agent8_renderer": {
                "elapsed_sec": a8_render.get("elapsed_sec"),
                "total_pages": a8_render.get("total_pages"),
                "sections": len(a8_render.get("section_files") or []),
            },
            "agent8_excel": {
                "elapsed_sec": a8_excel.get("elapsed_sec"),
                "size_bytes": a8_excel.get("size_bytes"),
                "sheets": a8_excel.get("sheets") or [],
            },
            "total_elapsed_sec": trace["total_elapsed_sec"],
        },
    }


def _file_manifest(job_id: str, render_meta: dict, excel_meta: dict) -> list[dict]:
    """Liệt kê toàn bộ file output để frontend hiển thị + cho phép download riêng từng cái."""
    items = []
    # Full PDF.
    full_size = render_meta.get("full_pdf_size_bytes") or 0
    full_pages = render_meta.get("total_pages") or 0
    items.append({
        "kind": "full",
        "title": "Báo cáo đầy đủ (toàn bộ 12 mục)",
        "category": "pdf_full",
        "format": "PDF",
        "pages": full_pages,
        "size_bytes": full_size,
        "url": f"/api/download/{job_id}/full",
    })
    # Per-section PDFs.
    for f in render_meta.get("section_files") or []:
        items.append({
            "kind": f["kind"],
            "title": f["title"],
            "category": "pdf_section",
            "format": "PDF",
            "pages": f["pages"],
            "size_bytes": f["size_bytes"],
            "url": f"/api/download/{job_id}/section/{f['kind']}",
        })
    # Excel.
    items.append({
        "kind": "excel",
        "title": "Dữ liệu tài chính (10 sheet)",
        "category": "excel",
        "format": "XLSX",
        "pages": None,
        "size_bytes": excel_meta.get("size_bytes") or 0,
        "url": f"/api/download/{job_id}/excel",
    })
    # Debug + trace.
    items.append({
        "kind": "debug",
        "title": "Debug PDF (trace mọi agent)",
        "category": "debug",
        "format": "PDF",
        "pages": None,
        "size_bytes": None,
        "url": f"/api/download/{job_id}/debug",
    })
    items.append({
        "kind": "trace",
        "title": "Trace JSON",
        "category": "debug",
        "format": "JSON",
        "pages": None,
        "size_bytes": None,
        "url": f"/api/download/{job_id}/trace",
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


# Map "kind" → file path inside job_dir. Section PDFs share a single template.
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
        "valuation": ("full.pdf",  "application/pdf",  f"dinh_gia_{job_id}.pdf"),  # legacy alias
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
