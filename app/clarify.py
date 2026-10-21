"""Clarify first: a few focused questions before searching, only where the answer changes the results.

Questions come from rules (no AI call, no cost): what the request leaves open for its category. Every
question can be skipped; the research then states what it assumed. Answers are stored per request so the
same question isn't asked again.
"""

from __future__ import annotations

import re
from typing import Any

from . import discovery as disc
from . import extract as ex

MAX_QUESTIONS = 4
_LENGTH_ITEM = re.compile(r"\b(cable|wire|teck|cord|conductor|rope|chain|hose|tubing|conduit)\b", re.I)
_CABLE = re.compile(r"\b(cable|wire|teck|cord|conductor)\b", re.I)
_UNIT = r"(ft\b\.?|feet\b|foot\b|'|m\b|metres?\b|meters?\b)"
_LENGTH_ANSWER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*" + _UNIT, re.I)
# "2 reels of 500 ft", "3 x 250 m": several lengths
_MULTI_LENGTH = re.compile(r"(\d{1,4})\s*(?:x|×|reels?|spools?|coils?|rolls?|lengths?|pieces?|pcs)\s*(?:of\s*|@\s*)?"
                           r"(\d[\d,]*(?:\.\d+)?)\s*" + _UNIT, re.I)


def key_for(query: str) -> str:
    return ex.normalize_query(query)


def _q(qid: str, text: str, why: str, kind: str = "text", options: list[str] | None = None,
       placeholder: str | None = None) -> dict[str, Any]:
    return {"id": qid, "text": text, "why": why, "kind": kind, "options": options or [],
            "placeholder": placeholder or ""}


def all_questions(query: str, quantity: int | None = None) -> list[dict[str, Any]]:
    """Every question that could change this request's results, most important first."""
    name = (query or "").strip()
    is_url = ex.classify_input(name) == "url"
    cat = disc.categorize(name)
    tokens = ex.model_tokens(name)
    specs, length = ex.request_specs(name)
    dims = {s["dim"] for s in specs}
    words = re.findall(r"[A-Za-z0-9]+", name)
    out: list[dict[str, Any]] = []
    if _LENGTH_ITEM.search(name) and not length and not is_url:
        out.append(_q("length", "How much do you need?", "It's sold by the foot, metre or reel: the length decides "
                      "the total and which listings can be compared.", placeholder="e.g. 300 ft or 100 m"))
    elif not quantity and not ex.pack_quantity(name):
        out.append(_q("quantity", "How many do you need?", "Totals, minimum orders and volume pricing depend on it.",
                      kind="number", placeholder="e.g. 10"))
    if not is_url and not tokens and len(words) <= 2 and cat.key != "property":
        out.append(_q("specifics", "Which exact item? Add the type, size, rating, brand or model, or paste a link.",
                      "A short description matches many different items; details keep unrelated results out.",
                      placeholder="e.g. 3/4 in drive, 1,000 ft-lb"))
    if cat.key == "electrical" and _CABLE.search(name) and not tokens:
        if "V" not in dims:
            out.append(_q("voltage", "What voltage rating?", "Cable for 600 V, 1000 V and 5 kV is priced very "
                          "differently; listings are checked against the rating you give.",
                          kind="choice", options=["600 V", "1000 V", "5 kV", "Not sure"]))
        if "conductor material" not in dims:
            out.append(_q("material", "Copper or aluminum conductors?", "Aluminum is usually much cheaper; mixing "
                          "them would compare different products.", kind="choice",
                          options=["Copper", "Aluminum", "Either"]))
    if cat.key in ("vehicle", "machinery", "property"):
        out.append(_q("budget_cad", "Rough budget (CAD)?", "Large purchases get a deeper search, and the budget "
                      "helps rule out what doesn't fit.", kind="number", placeholder="e.g. 45000"))
    if "used" in cat.channels or cat.key == "property":
        out.append(_q("used_ok", "Would used, refurbished or auction items be acceptable?",
                      "Adds used listings and auctions, which can cost much less (always shown separately from new).",
                      kind="choice", options=["Yes", "New only"]))
    if not tokens and not is_url:
        out.append(_q("intended_use", "What will it be used for?", "Helps choose the right grade or rating and rule "
                      "out unsuitable listings; it's also included in quote requests.",
                      placeholder="e.g. outdoor feeder to the dock crane"))
    out.append(_q("needed_by", "When do you need it?", "Decides whether slower, cheaper shipping or an import is "
                  "practical; included in quote requests.", placeholder="e.g. by Nov 15, or no rush"))
    return out


def questions(query: str, quantity: int | None = None, known: dict[str, Any] | None = None) -> dict[str, Any]:
    """Questions not yet answered (or skipped) for this request, at most MAX_QUESTIONS."""
    known = known or {}
    pending = [q for q in all_questions(query, quantity) if q["id"] not in known]
    return {"key": key_for(query), "category": disc.categorize(query).label, "questions": pending[:MAX_QUESTIONS],
            "known": known, "note": "Every question is optional. Skip any and the research says what it assumed."}


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        value = re.sub(r"\s+", " ", value).strip()[:200]
        return value or None
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value if 0 <= value < 1e9 else None
    return None


def apply_answers(query: str, answers: dict[str, Any] | None, quantity: int | None) -> dict[str, Any]:
    """What the answers change for the research, and the assumptions for questions left unanswered.

    Answers stored as None mean "skipped"."""
    raw = {k: _clean(v) for k, v in (answers or {}).items() if k in {q["id"] for q in all_questions(query, None)}
           or k in ("quantity", "used_ok", "intended_use", "needed_by")}
    asked = {q["id"]: q for q in all_questions(query, quantity)}
    out: dict[str, Any] = {"answers": raw, "quantity": quantity, "used_ok": True, "spec_text": "", "length_text": None,
                           "assumptions": [], "intended_use": raw.get("intended_use"),
                           "stated_budget": raw.get("budget_cad")}
    q = raw.get("quantity")
    if quantity is None and q is not None:
        try:
            n = int(float(str(q).replace(",", "")))
            out["quantity"] = n if 0 < n < 1_000_000 else None
        except ValueError:
            pass
    length = raw.get("length")
    length_unclear = None
    if length:
        multi = _MULTI_LENGTH.search(str(length))
        m = _LENGTH_ANSWER.search(str(length))
        if multi:
            total = int(multi.group(1)) * float(multi.group(2).replace(",", ""))
            out["length_text"] = f"{total:g} {multi.group(3)} of"
        elif m:
            out["length_text"] = f"{m.group(1)} {m.group(2)} of"
        else:
            length_unclear = str(length)
    used = raw.get("used_ok")
    if isinstance(used, str):
        out["used_ok"] = not used.lower().startswith("new")
    elif isinstance(used, bool):
        out["used_ok"] = used
    for qid in ("voltage", "material"):
        v = raw.get(qid)
        if v and v.lower() not in ("not sure", "either"):
            out["spec_text"] += f" {v}"
    if raw.get("specifics"):
        out["spec_text"] += f" {raw['specifics']}"
    a = out["assumptions"]
    if "quantity" in asked and out["quantity"] is None:
        a.append("Quantity not given: prices are compared per unit, with totals for one.")
    if "length" in asked and length_unclear:
        a.append(f"Length answer '{length_unclear}' has no unit (ft or m), so it wasn't used - enter e.g. "
                 f"'{length_unclear} ft' next time. Totals for your length can't be worked out.")
    elif "length" in asked and not out["length_text"]:
        a.append("Length not given: per-foot and per-reel prices are shown but totals for your length can't be "
                 "worked out.")
    if "voltage" in asked and (raw.get("voltage") or "").lower() in ("", "not sure"):
        a.append("Voltage rating not given: listings weren't checked for it - confirm the rating before ordering.")
    if "material" in asked and (raw.get("material") or "either").lower() == "either":
        a.append("Conductor material not fixed: copper and aluminum listings may both appear; check each one.")
    if "used_ok" in asked and used is None:
        a.append("Used and auction items included (you didn't say), always shown separately from new.")
    elif not out["used_ok"]:
        a.append("New only: used, refurbished and auction channels weren't searched.")
    if "intended_use" in asked and not raw.get("intended_use"):
        a.append("Intended use not given: listings are matched on the description only.")
    if "specifics" in asked and not raw.get("specifics"):
        a.append("Short description: results may include different types or sizes of the item.")
    if "budget_cad" in asked and raw.get("budget_cad") is None:
        a.append("No budget given: the search depth is based on the prices found.")
    if raw.get("needed_by") is None and "needed_by" in asked:
        a.append("No deadline given: delivery times are shown but don't rule anything out.")
    return out
