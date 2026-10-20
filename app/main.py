"""FastAPI application: JSON API + static single-page UI."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from . import extract as ex
from .config import Settings, load_settings
from .db import Database, iso
from .export import comparison_xlsx, offers_csv
from .providers import SETUP_INSTRUCTIONS, provider_status
from .research import ResearchEngine, ResearchError, ResearchRequest, observation_rows, reanalyze

log = logging.getLogger("purchasing")
STATIC_DIR = Path(__file__).parent / "static"


class ResearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=600)
    depth: str = "standard"
    quantity: int | None = Field(default=None, ge=1, le=10_000_000)
    force: bool = False
    comparison_id: int | None = None


class ComparisonPatch(BaseModel):
    saved: bool | None = None
    title: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)


class AssumptionsBody(BaseModel):
    assumptions: dict[str, Any] = Field(default_factory=dict)
    quantity: int | None = Field(default=None, ge=0, le=10_000_000)


@dataclass
class Job:
    id: str
    search_id: int
    query: str
    status: str = "running"  # running | done | failed
    step: str = "Starting"
    pct: int = 0
    comparison_id: int | None = None
    error: dict[str, Any] | None = None
    started_at: str = field(default_factory=iso)


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None,
               llm: Any | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = Database(settings.database_path)
    if llm is None and settings.llm_enabled:
        from .llm import ClaudeAnalyst
        llm = ClaudeAnalyst(settings)
    engine = ResearchEngine(settings, db, llm=llm, transport=transport)
    jobs: dict[str, Job] = {}
    tasks: set[asyncio.Task] = set()

    app = FastAPI(title="Purchasing Intelligence", version=__version__)
    app.state.settings, app.state.db, app.state.engine, app.state.jobs = settings, db, engine, jobs

    # ------------------------------------------------------------------ status
    @app.get("/api/status")
    def status() -> dict[str, Any]:
        st = provider_status(settings)
        return {**st, "version": __version__, "database": str(settings.database_path),
                "page_fetching": settings.fetch_pages, "robots_txt": settings.respect_robots_txt,
                "home_province": settings.home_province}

    # ---------------------------------------------------------------- research
    @app.post("/api/research")
    async def start_research(body: ResearchBody):
        if not provider_status(settings)["ready"]:
            return JSONResponse(status_code=503, content={"error": "not_configured",
                                                          "message": SETUP_INSTRUCTIONS["summary"],
                                                          "setup": SETUP_INSTRUCTIONS})
        query = body.query.strip()
        if not query:
            raise HTTPException(400, "Enter a product name, model number, description or URL.")
        normalized = ex.normalize_query(query)
        if not body.force and body.comparison_id is None:
            dup = db.find_recent_comparison(normalized, settings.duplicate_window_hours)
            if dup:
                return {"duplicate": dup, "message": "This was researched recently. Open the saved result, or "
                                                    "refresh to search again (uses search credits)."}
        if body.comparison_id is not None and not db.get_comparison(body.comparison_id):
            raise HTTPException(404, "Comparison not found")
        search_id = db.create_search(query, normalized, ex.classify_input(query), body.depth)
        # Forget finished jobs after a while (results live in the database, not here)
        for jid in [j.id for j in jobs.values() if j.status != "running" and len(jobs) > 200]:
            jobs.pop(jid, None)
        job = Job(id=uuid.uuid4().hex[:12], search_id=search_id, query=query)
        jobs[job.id] = job

        def progress(step: str, pct: int) -> None:
            job.step, job.pct = step, pct

        async def runner() -> None:
            try:
                req = ResearchRequest(query=query, depth=body.depth, quantity=body.quantity,
                                      comparison_id=body.comparison_id)
                result = await engine.run(req, progress)
                existing = db.get_comparison(body.comparison_id) if body.comparison_id else None
                if existing and existing.get("assumptions"):
                    result = reanalyze(result, existing["assumptions"], settings.home_province)
                cid = db.save_comparison(title=result["identity"]["name"][:200], query=query, normalized=normalized,
                                         product_key=result["product_key"], result=result,
                                         comparison_id=body.comparison_id)
                db.add_observations(observation_rows(result, cid, search_id))
                db.finish_search(search_id, "complete", cid)
                job.comparison_id, job.status, job.step, job.pct = cid, "done", "Done", 100
            except ResearchError as exc:
                job.status, job.error = "failed", {"kind": exc.kind, "message": str(exc), "details": exc.details}
                db.finish_search(search_id, "failed", error=str(exc))
            except Exception as exc:  # noqa: BLE001 - never leave a job hanging
                log.exception("research failed")
                job.status = "failed"
                job.error = {"kind": "internal", "message": f"Unexpected error: {type(exc).__name__}: {exc}"}
                db.finish_search(search_id, "failed", error=job.error["message"])

        task = asyncio.create_task(runner())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return JSONResponse(status_code=202, content={"job_id": job.id, "search_id": search_id})

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found (the server may have restarted)")
        return job.__dict__

    # ------------------------------------------------------------- comparisons
    @app.get("/api/comparisons")
    def list_comparisons(saved: bool = False, limit: int = 50) -> list[dict[str, Any]]:
        return db.list_comparisons(saved_only=saved, limit=min(limit, 200))

    @app.get("/api/comparisons/{cid}")
    def get_comparison(cid: int) -> dict[str, Any]:
        comp = db.get_comparison(cid)
        if not comp:
            raise HTTPException(404, "Comparison not found")
        return comp

    @app.patch("/api/comparisons/{cid}")
    def patch_comparison(cid: int, body: ComparisonPatch) -> dict[str, Any]:
        if not db.get_comparison(cid):
            raise HTTPException(404, "Comparison not found")
        db.update_comparison_meta(cid, saved=body.saved, title=body.title, notes=body.notes)
        return db.get_comparison(cid)

    @app.put("/api/comparisons/{cid}/assumptions")
    def put_assumptions(cid: int, body: AssumptionsBody) -> dict[str, Any]:
        comp = db.get_comparison(cid)
        if not comp:
            raise HTTPException(404, "Comparison not found")
        result = reanalyze(comp["result"], body.assumptions, settings.home_province, body.quantity)
        db.update_comparison_meta(cid, assumptions=result["assumptions"], result=result)
        return db.get_comparison(cid)

    @app.delete("/api/comparisons/{cid}")
    def delete_comparison(cid: int) -> dict[str, Any]:
        if not db.delete_comparison(cid):
            raise HTTPException(404, "Comparison not found")
        return {"deleted": cid}

    @app.get("/api/comparisons/{cid}/export.csv")
    def export_csv(cid: int) -> Response:
        comp = db.get_comparison(cid)
        if not comp:
            raise HTTPException(404, "Comparison not found")
        return Response(offers_csv(comp["result"]), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="comparison-{cid}.csv"'})

    @app.get("/api/comparisons/{cid}/export.xlsx")
    def export_xlsx(cid: int) -> Response:
        comp = db.get_comparison(cid)
        if not comp:
            raise HTTPException(404, "Comparison not found")
        history = db.observations(product_key=comp["product_key"]) if comp.get("product_key") else []
        return Response(comparison_xlsx(comp, history),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="comparison-{cid}.xlsx"'})

    @app.get("/api/comparisons/{cid}/history")
    def comparison_history(cid: int) -> dict[str, Any]:
        comp = db.get_comparison(cid)
        if not comp:
            raise HTTPException(404, "Comparison not found")
        return price_history(db.observations(product_key=comp["product_key"]) if comp.get("product_key") else [])

    # ---------------------------------------------------------------- searches
    @app.get("/api/searches/recent")
    def recent(limit: int = 20) -> list[dict[str, Any]]:
        return db.recent_searches(min(limit, 100))

    # ------------------------------------------------------------------ static
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def price_history(obs: list[dict[str, Any]]) -> dict[str, Any]:
    """Real observations only. A chart is offered only with enough comparable data."""
    usable = [o for o in obs if o.get("price_cad") is not None and o.get("match_level") in ("exact", "unverified")
              and (o.get("condition") in (None, "new")) and o.get("price_type") == "listed"]
    dates = {o["observed_at"][:10] for o in usable}
    by_supplier: dict[str, list[dict[str, Any]]] = {}
    for o in usable:
        by_supplier.setdefault(o["supplier"] or o["supplier_domain"], []).append(
            {"observed_at": o["observed_at"], "price_cad": o["price_cad"], "price": o["price"],
             "currency": o["currency"], "pack_qty": o["pack_qty"], "url": o["url"], "basis": o["price_basis"]})
    pack_sizes = {o.get("pack_qty") for o in usable}
    chartable = len(usable) >= 3 and len(dates) >= 2 and len(pack_sizes) <= 1
    if chartable:
        reason = None
    elif len(pack_sizes) > 1:
        reason = "Observations cover different pack sizes, so they are listed rather than charted."
    else:
        reason = (f"Not enough comparable history to chart yet ({len(usable)} comparable observation(s) on "
                  f"{len(dates)} day(s); need at least 3 on 2+ days). Showing the actual observations instead.")
    return {"chartable": chartable, "reason": reason, "series": by_supplier, "observations": obs,
            "comparable_count": len(usable), "days": sorted(dates)}


app = None  # created by run.py / uvicorn factory


def get_app() -> FastAPI:
    return create_app()
