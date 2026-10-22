"""FastAPI application: JSON API + static single-page UI."""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from . import clarify as cl
from . import extract as ex
from .config import Settings, load_settings, save_env_values
from .costs import PRICES_CHECKED, PRICES_PER_MTOK, estimate_usd
from .db import Database, iso
from .export import comparison_xlsx, offers_csv
from .llm import LlmError
from .providers import SETUP_INSTRUCTIONS, provider_status
from .research import ANALYSIS_VERSION, ResearchEngine, ResearchError, ResearchRequest, observation_rows, reanalyze

log = logging.getLogger("purchasing")
STATIC_DIR = Path(__file__).parent / "static"


class Filters(BaseModel):
    """Search filters; each is optional. Prices in CAD."""
    price_min: float | None = Field(default=None, ge=0, le=100_000_000)
    price_max: float | None = Field(default=None, ge=0, le=100_000_000)
    year_min: int | None = Field(default=None, ge=1900, le=2100)
    year_max: int | None = Field(default=None, ge=1900, le=2100)
    km_max: int | None = Field(default=None, ge=0, le=10_000_000)
    hours_max: int | None = Field(default=None, ge=0, le=1_000_000)


class ResearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=600)
    depth: str = "standard"
    quantity: int | None = Field(default=None, ge=1, le=10_000_000)
    force: bool = False
    comparison_id: int | None = None
    # where to look: Thunder Bay only, outside Thunder Bay only, or both (the default)
    area: Literal["both", "local", "outside"] = "both"
    filters: Filters | None = None
    # answers to the clarifying questions; None = skipped. Stored, and merged with earlier answers.
    answers: dict[str, str | int | float | bool | None] | None = None


def verdict(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """A comparison's outcome in a few words, for the saved and recent lists."""
    plain = (result or {}).get("recommendation")
    if not plain:
        return None
    if plain.get("lead"):
        row = next((r for r in plain.get("comparison", []) if r.get("offer_id") == plain["lead"]["offer_id"]), {})
        return {"kind": "ok", "text": row.get("price") or "Recommended", "who": plain["lead"].get("supplier")}
    if plain.get("judge") == "shortlist":
        return {"kind": "hold", "text": "Shortlist"}
    if plain.get("judge"):
        return {"kind": "hold", "text": "For you to judge"}
    return {"kind": "hold", "text": "Quote needed"}


class PhotoBody(BaseModel):
    # a data URL from the browser ("data:image/jpeg;base64,..."), already shrunk to about 1600 px by the page
    image: str = Field(min_length=20, max_length=8_000_000)


PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
PHOTO_MAX_BYTES = 4_500_000  # under the API's 5 MB per-image limit
GOOGLE_LENS = "https://lens.google.com/"


class ClarifyBody(BaseModel):
    query: str = Field(min_length=1, max_length=600)
    quantity: int | None = Field(default=None, ge=1, le=10_000_000)


class KeysBody(BaseModel):
    anthropic_api_key: str | None = Field(default=None, max_length=300)
    tavily_api_key: str | None = Field(default=None, max_length=300)
    serpapi_api_key: str | None = Field(default=None, max_length=300)


# field -> (.env name, what it looks like, accepted format)
KEY_FORMATS = {"anthropic_api_key": ("ANTHROPIC_API_KEY", "it should start with 'sk-ant-'",
                                     re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
               "tavily_api_key": ("TAVILY_API_KEY", "it should start with 'tvly-'",
                                  re.compile(r"tvly-[A-Za-z0-9_\-]{10,}")),
               "serpapi_api_key": ("SERPAPI_API_KEY", "it's a long code of letters and numbers from "
                                   "serpapi.com/manage-api-key", re.compile(r"[A-Za-z0-9]{32,100}"))}
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
KeyChecker = Callable[[str], Awaitable[str | None]]


async def check_anthropic_key(key: str, base_url: str = "https://api.anthropic.com") -> str | None:
    """None if Anthropic accepts the key, else a message. Lists models, which uses no tokens."""
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=key, base_url=base_url, timeout=20, max_retries=1)
    try:
        await client.models.list(limit=1)
    except anthropic.AuthenticationError:
        return "Anthropic rejected this key. Check that you copied all of it."
    except anthropic.PermissionDeniedError:
        return "This key isn't allowed to use the Anthropic API."
    except anthropic.APIConnectionError:
        return "Couldn't reach Anthropic to check the key. Check the internet connection and try again."
    except anthropic.APIStatusError as exc:
        return f"Anthropic returned an error ({exc.status_code}) while checking the key. Try again shortly."
    finally:
        await client.close()
    return None


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
               llm: Any | None = None, anthropic_client: Any | None = None,
               key_checker: KeyChecker | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = Database(settings.database_path)
    own_llm = llm is None  # rebuilt when a key is saved from the UI
    if llm is None and settings.llm_enabled:
        from .llm import ClaudeAnalyst
        llm = ClaudeAnalyst(settings)
    engine = ResearchEngine(settings, db, llm=llm, transport=transport, anthropic_client=anthropic_client)
    jobs: dict[str, Job] = {}
    tasks: set[asyncio.Task] = set()

    app = FastAPI(title="Purchasing Intelligence", version=__version__)
    app.state.settings, app.state.db, app.state.engine, app.state.jobs = settings, db, engine, jobs

    # ------------------------------------------------------------------ status
    def spend() -> dict[str, Any]:
        return {"month_usd": round(db.month_spend(), 2), "budget_usd": settings.monthly_budget_usd,
                "model": settings.anthropic_model if settings.anthropic_api_key else None,
                "estimable": settings.anthropic_model in PRICES_PER_MTOK, "prices_checked": PRICES_CHECKED}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        st = provider_status(settings)
        return {**st, "version": __version__, "database": str(settings.database_path),
                "page_fetching": settings.fetch_pages, "robots_txt": settings.respect_robots_txt,
                "fetch_fallback": settings.fetch_fallback_enabled,
                "home_province": settings.home_province, "spend": spend(),
                "ai_key_rejected": bool(engine.llm is not None and getattr(engine.llm, "key_rejected", False))}

    # ------------------------------------------------------------------- setup
    def require_local(request: Request) -> None:
        """Keys may be saved only by a browser on the machine running the app, from this app's own page."""
        client_host = request.client.host if request.client else ""
        ok = client_host in LOCAL_HOSTS and (request.url.hostname or "") in LOCAL_HOSTS
        origin = request.headers.get("origin")
        if origin:
            o = urlsplit(origin)
            ok = ok and o.hostname in LOCAL_HOSTS and o.port == request.url.port
        if not ok:
            raise HTTPException(403, "Keys can only be saved from the computer running the app "
                                     "(open it at http://127.0.0.1).")
        if "application/json" not in request.headers.get("content-type", ""):
            raise HTTPException(415, "Send the keys as JSON.")

    @app.post("/api/setup/keys")
    async def save_keys(body: KeysBody, request: Request) -> dict[str, Any]:
        require_local(request)
        values: dict[str, str] = {}
        for fld, (env_name, hint, fmt) in KEY_FORMATS.items():
            raw = (getattr(body, fld) or "").strip()
            if not raw:
                continue
            if not fmt.fullmatch(raw):
                raise HTTPException(400, f"That doesn't look like a {env_name} ({hint}).")
            values[env_name] = raw
        if not values:
            raise HTTPException(400, "Paste a key first.")
        if "ANTHROPIC_API_KEY" in values:
            problem = await (key_checker or (lambda k: check_anthropic_key(k, settings.anthropic_base_url)))(
                values["ANTHROPIC_API_KEY"])
            if problem:
                raise HTTPException(400, problem)
        save_env_values(settings.env_file, values)
        if "ANTHROPIC_API_KEY" in values:
            settings.anthropic_api_key = values["ANTHROPIC_API_KEY"]
            if own_llm:
                from .llm import ClaudeAnalyst
                engine.llm = ClaudeAnalyst(settings)
        if "TAVILY_API_KEY" in values:
            settings.tavily_api_key = values["TAVILY_API_KEY"]
        if "SERPAPI_API_KEY" in values:
            settings.serpapi_api_key = values["SERPAPI_API_KEY"]
        log.info("saved %s to %s", ", ".join(values), settings.env_file)
        return {"saved": sorted(values), "ready": provider_status(settings)["ready"]}

    # ---------------------------------------------------------------- research
    @app.post("/api/clarify")
    def clarify(body: ClarifyBody) -> dict[str, Any]:
        """Questions worth answering before this research (rules only - no search, no AI, no cost)."""
        query = body.query.strip()
        return cl.questions(query, body.quantity, db.get_answers(cl.key_for(query)))

    @app.post("/api/photo")
    async def read_photo(body: PhotoBody):
        """What a photo shows and a search for it, read by Claude. The photo goes only to Anthropic and isn't
        stored. Nothing is searched until the person confirms or edits the suggestion."""
        lens = {"google_lens": GOOGLE_LENS}
        if engine.llm is None:
            return JSONResponse(status_code=503, content={
                "error": "no_ai", **lens, "message": "Reading a photo needs the Anthropic key (Data sources > Add "
                                                     "or change API keys). You can still try Google Lens."})
        m = re.fullmatch(r"data:(image/[a-z+]+);base64,([A-Za-z0-9+/=\s]+)", body.image.strip())
        if not m or m.group(1) not in PHOTO_TYPES:
            raise HTTPException(400, "Use a JPEG, PNG, WebP or GIF photo.")
        try:
            raw = base64.b64decode(m.group(2), validate=False)
        except (binascii.Error, ValueError):
            raise HTTPException(400, "That photo couldn't be read. Try taking it again.") from None
        if len(raw) > PHOTO_MAX_BYTES:
            raise HTTPException(413, "That photo is too large (over 4.5 MB). Try a smaller one.")
        if settings.monthly_budget_usd > 0 and db.month_spend() >= settings.monthly_budget_usd:
            return JSONResponse(status_code=402, content={"error": "budget", **lens,
                                                          "message": "This month's AI spending limit is reached."})
        try:
            found = await engine.llm.identify_photo(m.group(1), base64.b64encode(raw).decode())
        except LlmError as exc:
            return JSONResponse(status_code=502, content={"error": "ai", **lens,
                                                          "message": f"The photo couldn't be read: {exc}."})
        usage = found.pop("_usage", None)
        cost = estimate_usd({"llm_usage": {"photo": usage}})
        db.record_spend(f"Photo: {found['what'] or 'unidentified item'}"[:200], "photo", cost)
        return {**found, **lens, "cost_usd": cost,
                "label": "AI reading of your photo - check it, and edit the search if needed, before searching."}

    @app.post("/api/research")
    async def start_research(body: ResearchBody):
        if not provider_status(settings)["ready"]:
            return JSONResponse(status_code=503, content={"error": "not_configured",
                                                          "message": SETUP_INSTRUCTIONS["summary"],
                                                          "setup": SETUP_INSTRUCTIONS})
        query = body.query.strip()
        if not query:
            raise HTTPException(400, "Enter a product name, model number, description or URL.")
        # a Thunder Bay-only (or outside-only) search is a different search from the same words everywhere
        normalized = ex.normalize_query(query) + ("" if body.area == "both" else f" [{body.area}]")
        if not body.force and body.comparison_id is None:
            dup = db.find_recent_comparison(normalized, settings.duplicate_window_hours)
            if dup:
                return {"duplicate": dup, "message": "This was researched recently. Open the saved result, or "
                                                    "refresh to search again (uses search credits)."}
        if body.comparison_id is not None and not db.get_comparison(body.comparison_id):
            raise HTTPException(404, "Comparison not found")
        if settings.monthly_budget_usd > 0 and settings.anthropic_api_key:
            spent = db.month_spend()
            if spent >= settings.monthly_budget_usd:
                return JSONResponse(status_code=402, content={
                    "error": "budget",
                    "message": f"This month's spending limit of US${settings.monthly_budget_usd:.2f} is reached "
                               f"(about US${spent:.2f} used, estimated). New research starts again on the 1st, "
                               "or raise PI_MONTHLY_BUDGET_USD in the .env file and restart."})
        if body.answers:
            db.save_answers(cl.key_for(query), query, {k: v for k, v in body.answers.items() if len(k) <= 40})
        applied = cl.apply_answers(query, db.get_answers(cl.key_for(query)), body.quantity)
        search_id = db.create_search(query, normalized, ex.classify_input(query), body.depth)
        # Forget finished jobs after a while (results live in the database, not here)
        for jid in [j.id for j in jobs.values() if j.status != "running" and len(jobs) > 200]:
            jobs.pop(jid, None)
        job = Job(id=uuid.uuid4().hex[:12], search_id=search_id, query=query)
        jobs[job.id] = job

        def progress(step: str, pct: int) -> None:
            job.step, job.pct = step, pct

        meter: dict[str, Any] = {}

        def cost() -> float | None:  # also counts what a failed or stopped research had already used
            return estimate_usd(meter["credits"]()) if "credits" in meter else None

        async def runner() -> None:
            try:
                req = ResearchRequest(query=query, depth=body.depth, quantity=applied["quantity"],
                                      comparison_id=body.comparison_id, used_ok=applied["used_ok"],
                                      answers=applied["answers"], assumptions=applied["assumptions"],
                                      spec_text=applied["spec_text"], length_text=applied["length_text"],
                                      intended_use=applied["intended_use"], area=body.area,
                                      filters=body.filters.model_dump(exclude_none=True) if body.filters else {})
                result = await asyncio.wait_for(engine.run(req, progress, meter), timeout=settings.job_timeout_s)
                existing = db.get_comparison(body.comparison_id) if body.comparison_id else None
                if existing and existing.get("assumptions"):
                    result = reanalyze(result, existing["assumptions"], settings.home_province)
                cid = db.save_comparison(title=result["identity"]["name"][:200], query=query, normalized=normalized,
                                         product_key=result["product_key"], result=result,
                                         comparison_id=body.comparison_id)
                db.add_observations(observation_rows(result, cid, search_id))
                db.finish_search(search_id, "complete", cid, cost_usd=cost())
                job.comparison_id, job.status, job.step, job.pct = cid, "done", "Done", 100
            except ResearchError as exc:
                job.status, job.error = "failed", {"kind": exc.kind, "message": str(exc), "details": exc.details}
                db.finish_search(search_id, "failed", error=str(exc), cost_usd=cost())
            except asyncio.TimeoutError:
                msg = f"Research took longer than {settings.job_timeout_s:.0f}s and was stopped."
                job.status, job.error = "failed", {"kind": "timeout", "message": msg}
                db.finish_search(search_id, "failed", error=msg, cost_usd=cost())
            except Exception as exc:  # noqa: BLE001 - never leave a job hanging
                log.exception("research failed")
                job.status = "failed"
                job.error = {"kind": "internal", "message": f"Unexpected error: {type(exc).__name__}: {exc}"}
                db.finish_search(search_id, "failed", error=job.error["message"], cost_usd=cost())

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
        rows = db.list_comparisons(saved_only=saved, limit=min(limit, 200))
        results = db.results_for([r["id"] for r in rows])
        return [r | {"verdict": verdict(results.get(r["id"]))} for r in rows]

    @app.get("/api/comparisons/{cid}")
    def get_comparison(cid: int) -> dict[str, Any]:
        comp = db.get_comparison(cid)
        if not comp:
            raise HTTPException(404, "Comparison not found")
        if (comp["result"].get("analysis_version") or 1) < ANALYSIS_VERSION:
            # saved by an older version: apply the current comparison rules to the stored evidence
            try:
                result = reanalyze(comp["result"], comp.get("assumptions") or {}, settings.home_province)
            except Exception:  # noqa: BLE001 - show the saved result rather than fail
                log.exception("re-analysis of comparison %s failed", cid)
                return comp
            db.update_comparison_meta(cid, result=result)
            comp = db.get_comparison(cid)
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

    @app.put("/api/comparisons/{cid}/filters")
    def put_filters(cid: int, body: Filters) -> dict[str, Any]:
        """Apply new filters to a saved result (no new searching, no credits)."""
        comp = db.get_comparison(cid)
        if not comp:
            raise HTTPException(404, "Comparison not found")
        result = dict(comp["result"])
        result["filters"] = body.model_dump(exclude_none=True)
        result = reanalyze(result, comp.get("assumptions") or {}, settings.home_province)
        db.update_comparison_meta(cid, result=result)
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
    @app.delete("/api/searches/recent")
    def clear_recent() -> dict[str, Any]:
        """Clears the recent-searches list (saved comparisons and price history are kept)."""
        return {"cleared": db.clear_recent_searches()}

    @app.get("/api/searches/recent")
    def recent(limit: int = 20) -> list[dict[str, Any]]:
        rows = db.recent_searches(min(limit, 100))
        results = db.results_for([r["comparison_id"] for r in rows if r["comparison_id"]])
        return [r | {"verdict": verdict(results.get(r["comparison_id"]))} for r in rows]

    # ------------------------------------------------------------------ static
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def price_history(obs: list[dict[str, Any]]) -> dict[str, Any]:
    """Real observations only. A chart is offered only with enough comparable data."""
    # Only exact model matches can form a price trend; without a model number the listings may be
    # different products, so they are listed but never charted as one line.
    usable = [o for o in obs if o.get("price_cad") is not None and o.get("match_level") == "exact"
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
    elif obs and not any(o.get("match_level") == "exact" for o in obs):
        reason = ("No model number was given, so listings may be different products and aren't charted as one "
                  "price trend. Showing the actual observations instead.")
    else:
        reason = (f"Not enough comparable history to chart yet ({len(usable)} exact-model observation(s) on "
                  f"{len(dates)} day(s); need at least 3 on 2+ days). Showing the actual observations instead.")
    return {"chartable": chartable, "reason": reason, "series": by_supplier, "observations": obs,
            "comparable_count": len(usable), "days": sorted(dates)}


app = None  # created by run.py / uvicorn factory


def _open_browser_when_ready(url: str, timeout_s: float = 60.0) -> None:
    """Open `url` in the default browser once the server accepts connections (for the double-click starters)."""
    import socket
    import threading
    import time
    import webbrowser

    parts = urlsplit(url)
    host, port = parts.hostname or "127.0.0.1", parts.port or 80

    def wait_and_open() -> None:
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            try:
                with socket.create_connection((host, port), timeout=1):
                    webbrowser.open(url)
                    return
            except OSError:
                time.sleep(0.4)

    threading.Thread(target=wait_and_open, daemon=True).start()


def get_app() -> FastAPI:
    import os

    app = create_app()
    if os.environ.get("PI_OPEN_BROWSER"):
        _open_browser_when_ready(os.environ["PI_OPEN_BROWSER"])
    return app
