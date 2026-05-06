"""FastAPI orchestrator: SME Valuation Report — 7 agents."""
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
from agents.extractor import extract
from agents.industry import analyze_industry
from agents.projector import project
from agents.renderer import render_report, render_valuation_report
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
    valuation_pdf_path = OUTPUT_DIR / f"{job_id}_valuation.pdf"
    debug_pdf_path = OUTPUT_DIR / f"{job_id}_debug.pdf"
    trace_path = OUTPUT_DIR / f"{job_id}_trace.json"
    upload_path.write_bytes(contents)

    pipeline_start = time.time()
    trace: dict = {
        "job_id": job_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        # ---- Agent 1: extract financials (sequential, blocks all downstream)
        log.info("[%s] agent1: extracting financials", job_id)
        a1 = await asyncio.to_thread(extract, str(upload_path))
        trace["agent1_extract"] = a1
        log.info("[%s] agent1 done in %.2fs", job_id, a1["elapsed_sec"])
        financials = a1.get("financials") or {}
        if not financials:
            raise HTTPException(422, "Không trích xuất được dữ liệu tài chính.")

        # ---- Agents 2 + 4 in parallel (industry analysis + ratio compute, no deps)
        log.info("[%s] agents 2+4 in parallel: industry, ratios", job_id)
        a2_industry, a4_ratios = await asyncio.gather(
            asyncio.to_thread(analyze_industry, financials),
            asyncio.to_thread(analyze, financials),
        )
        trace["agent2_industry"] = a2_industry
        trace["agent4_ratios"] = a4_ratios

        # ---- Agent 3: business_profile (needs industry)
        log.info("[%s] agent3: business profile", job_id)
        a3_business = await asyncio.to_thread(
            analyze_business, financials, a2_industry.get("industry") or {}
        )
        trace["agent3_business"] = a3_business

        # ---- Agent 5: projector (needs financials + ratios + industry)
        log.info("[%s] agent5: projecting 5y", job_id)
        a5_projection = await asyncio.to_thread(
            project, financials, a4_ratios, a2_industry.get("industry") or {}
        )
        trace["agent5_projector"] = a5_projection

        # ---- Agent 6: valuator (needs projection)
        log.info("[%s] agent6: valuation", job_id)
        a6_valuation = await asyncio.to_thread(
            compute_valuation, financials, a4_ratios,
            a2_industry.get("industry") or {}, a5_projection,
        )
        trace["agent6_valuator"] = a6_valuation

        # ---- Agent 7: thesis writer (needs everything)
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

        # ---- Agent 8: render PDF
        log.info("[%s] agent8: rendering valuation report PDF", job_id)
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
            render_valuation_report, payload, str(valuation_pdf_path)
        )
        trace["agent8_renderer"] = a8_render
        log.info("[%s] agent8 done: %d pages", job_id, a8_render["pages"])

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
                "pages": a8_render.get("pages"),
            },
            "total_elapsed_sec": trace["total_elapsed_sec"],
        },
        "valuation_url": f"/api/download/{job_id}/valuation",
        "debug_url": f"/api/download/{job_id}/debug",
        "trace_url": f"/api/download/{job_id}/trace",
    }


def _meta(payload):
    if not isinstance(payload, dict):
        return {}
    return {
        "model": payload.get("model"),
        "elapsed_sec": payload.get("elapsed_sec"),
        "usage": payload.get("usage"),
    }


@app.get("/api/download/{job_id}/{kind}")
def download(job_id: str, kind: str) -> FileResponse:
    if not _safe_job_id(job_id):
        raise HTTPException(400, "Invalid job_id")
    mapping = {
        "valuation": (f"{job_id}_valuation.pdf", "application/pdf",
                      f"dinh_gia_DN_{job_id}.pdf"),
        "debug": (f"{job_id}_debug.pdf", "application/pdf",
                  f"debug_{job_id}.pdf"),
        "trace": (f"{job_id}_trace.json", "application/json",
                  f"trace_{job_id}.json"),
    }
    if kind not in mapping:
        raise HTTPException(400, "Invalid kind. Use: valuation | debug | trace")
    fname, mime, dl_name = mapping[kind]
    fpath = OUTPUT_DIR / fname
    if not fpath.exists():
        raise HTTPException(404, f"{kind} not found for job {job_id}")
    return FileResponse(fpath, media_type=mime, filename=dl_name)


def _safe_job_id(job_id: str) -> bool:
    return job_id.isalnum() and 1 <= len(job_id) <= 32
