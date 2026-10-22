"""Short buying guides for broad terms ("radios", "work lights"): the main types and what each is for, the few
questions that change the answer at a terminal, rail yard or warehouse, and what to confirm with the supplier.

This is general guidance written into the app, not research: it's labelled that way everywhere it's shown, it names
no products or prices, and every point is something to verify with the supplier or your safety lead. Picking a type
turns the broad term into a focused search. Kept deliberately small: add a guide only for something bought often.
"""

from __future__ import annotations

import re
from typing import Any

LABEL = "General guidance built into the app - not from a search. Verify each point with the supplier."

_HAZARDOUS_Q = {"id": "g_hazardous", "kind": "choice", "options": ["No", "Yes", "Not sure"],
                "text": "Will any be used in a classified hazardous area (for example combustible dust or flammable "
                        "vapour)?",
                "why": "Those areas need equipment certified for the area's classification; ordinary equipment must "
                       "not be used there."}

GUIDES: list[dict[str, Any]] = [
    {
        "key": "radios", "title": "Two-way radios",
        "broad": r"(?:two[- ]way )?radios?|walkie[- ]?talkies?",
        "match": r"\b(?:two[- ]way radios?|walkie[- ]?talkies?|handheld radios?|portable radios?|mobile radios?|"
                 r"base station radios?|radio repeaters?|push[- ]to[- ]talk)\b",
        "intro": "Most sites use a mix: handhelds for people on foot, mobile radios in equipment, and a base station "
                 "or repeater for the control room and range.",
        "types": [
            {"name": "Portable two-way radios (handhelds)", "search": "portable two-way radio",
             "for": "Workers on foot: yard crews, warehouse staff, spotters and signal persons."},
            {"name": "Mobile radios (vehicle-mounted)", "search": "mobile two-way radio vehicle mount",
             "for": "Installed in loaders, trucks, locomotives and other equipment; more power and range than "
                    "handhelds."},
            {"name": "Base station or repeater", "search": "two-way radio base station repeater",
             "for": "A fixed radio in a control room or office; a repeater extends range across a large site."},
            {"name": "Push-to-talk over cellular", "search": "push to talk over cellular radio",
             "for": "Radio-style talk over the cell network: wide coverage where there is signal, monthly fees, "
                    "no radio licence of your own."},
        ],
        "questions": [
            {"id": "g_current", "kind": "text", "placeholder": "e.g. Motorola XPR 3300, or none",
             "text": "What radios do you use now (brand and model), if any?",
             "why": "New radios must work with your existing ones: same channels and the same mode (analog or the "
                    "same digital system). Included in quote requests."},
            {"id": "g_where", "kind": "choice", "options": ["Outdoor yard / dock", "Warehouse / indoors",
                                                            "In vehicles or equipment", "A mix"],
             "text": "Where will they mostly be used?", "why": "Decides toughness, range and noise handling."},
            _HAZARDOUS_Q,
        ],
        "checklist": [
            "Works with your current radios: same frequencies/channels and the same mode (analog, or the same "
            "digital system such as DMR). Ask who will program them.",
            "Licensing: business radios in Canada usually use frequencies licensed through ISED Canada - check that "
            "your licence covers the new radios.",
            "Toughness: dust and water rating (IP rating, e.g. IP67) and drop rating for outdoor and cold use.",
            "Noise: loud audio or noise-cancelling microphones, and earpieces or headsets that work with hearing "
            "protection.",
            "Battery: lasts a full shift in the cold; spare batteries and multi-unit chargers.",
            "Service: local programming, repair and warranty support.",
        ],
        # camping and family walkie-talkies (licence-free FRS/GMRS): short range, not built for industrial work
        "consumer": r"\b(?:camping|hiking|kids|family|toys?|FRS|GMRS)\b",
        "hazard": "Hazardous areas need intrinsically safe radios certified for that area's classification (marks "
                  "such as CSA, UL, ATEX or IECEx). Confirm the classification with your safety lead before ordering.",
    },
    {
        "key": "work_lights", "title": "Work lights",
        "broad": r"(?:work|job ?site|site|area|portable) lights?|work lighting",
        "match": r"\b(?:work ?lights?|light towers?|flood ?lights?|area lights?|portable lights?)\b",
        "intro": "Pick by the job: portable lights for repairs and inspections, light towers for night work in "
                 "open areas, fixed fixtures for permanent lighting.",
        "types": [
            {"name": "Portable LED work lights", "search": "portable LED work light",
             "for": "Handheld, stand or magnetic lights for repairs and inspections; battery or plug-in."},
            {"name": "Light towers", "search": "LED light tower",
             "for": "Mast lights on a trailer or skid for lighting yards or work zones at night; diesel, battery or "
                    "solar."},
            {"name": "Fixed area / flood lights", "search": "LED area flood light",
             "for": "Mounted on buildings or poles for permanent lighting of docks, yards and loading areas."},
            {"name": "Hazardous-location lights", "search": "hazardous location LED work light",
             "for": "Fixtures certified for classified hazardous areas."},
        ],
        "questions": [
            {"id": "g_where", "kind": "choice", "options": ["Outdoor yard / dock", "Indoors / warehouse",
                                                            "Tanks or confined spaces", "A mix"],
             "text": "Where will they be used?", "why": "Decides brightness, beam, weather rating and mounting."},
            {"id": "g_power", "kind": "choice", "options": ["Battery", "Plug-in (120 V)", "Hard-wired",
                                                            "Diesel or solar (towers)", "Not sure"],
             "text": "How will they be powered?", "why": "Rules out whole types and changes the cost."},
            _HAZARDOUS_Q,
        ],
        "checklist": [
            "Brightness (lumens) and beam spread for the area you need to light.",
            "Electrical certification for Canada: a CSA, cUL or cETL mark.",
            "Water and dust rating (IP rating) for outdoor and wash-down use.",
            "Cold-weather performance: battery run time drops in the cold.",
            "Run time per charge or per tank, and charging or refuelling.",
            "Mounting and cords: stands, magnets, hooks, cord length.",
        ],
        "hazard": "In classified hazardous areas or confined spaces, use lights certified for that classification. "
                  "Confirm with your safety lead.",
    },
    {
        "key": "air_compressors", "title": "Air compressors",
        "broad": r"(?:air )?compressors?",
        "match": r"\bair compressors?\b|\b(?:rotary screw|reciprocating|piston|portable|towable) (?:air )?compressors?\b",
        "intro": "Size a compressor by the air flow (CFM) at the pressure (PSI) your tools need, then by power "
                 "supply and how long it runs.",
        "types": [
            {"name": "Portable electric compressors", "search": "portable electric air compressor",
             "for": "Small air tools and tire inflation in a shop or service truck."},
            {"name": "Stationary shop compressors", "search": "stationary rotary screw air compressor",
             "for": "Plant air for shops and maintenance bays; rotary screw types suit long or continuous running."},
            {"name": "Towable diesel compressors", "search": "towable diesel air compressor",
             "for": "Field and yard work away from power: air tools, blowing down, sandblasting."},
        ],
        "questions": [
            {"id": "g_tools", "kind": "text", "placeholder": "e.g. two 1/2 in impact wrenches and a blow gun",
             "text": "What will it run, and how many at once?",
             "why": "The air flow (CFM) your tools use at once sets the size."},
            {"id": "g_power", "kind": "choice", "options": ["120 V", "240 V single-phase", "600 V three-phase",
                                                            "No power (diesel)", "Not sure"],
             "text": "What power is available?", "why": "The motor has to match your supply."},
            {"id": "g_duty", "kind": "choice", "options": ["Occasional", "Most of a shift", "Continuous"],
             "text": "How long will it run each day?", "why": "Long running needs a higher duty cycle (often "
                                                              "rotary screw)."},
        ],
        "checklist": [
            "Air flow (CFM) at your working pressure (PSI) covers the tools you'll run at once, with margin.",
            "Power supply matches (voltage and phase), or the engine and fuel for towable units.",
            "Duty cycle suits how long it runs each day.",
            "Moisture control: dryer, filters and drains (air lines can freeze in winter).",
            "Noise level if it runs indoors.",
            "Pressure vessel rules: in Ontario some air receivers must be registered or inspected (TSSA) - ask the "
            "supplier.",
            "Local service and parts.",
        ],
        "hazard": None,
    },
    {
        "key": "safety_glasses", "title": "Safety glasses and goggles",
        "broad": r"(?:safety )?(?:glasses|eyewear|goggles)",
        "match": r"\bsafety (?:glasses|eyewear|goggles)\b|\bgoggles\b",
        "intro": "Choose by the hazard first (impact, dust, splash, welding), then by conditions (glare, fogging) and "
                 "fit.",
        "types": [
            {"name": "Safety glasses", "search": "safety glasses CSA Z94.3",
             "for": "Everyday protection from flying particles."},
            {"name": "Safety goggles", "search": "safety goggles CSA Z94.3",
             "for": "Seal around the eyes for dust, grain or chemical splash."},
            {"name": "Over-the-glasses (OTG)", "search": "over the glasses safety glasses",
             "for": "Fit over prescription glasses."},
            {"name": "Prescription safety glasses", "search": "prescription safety glasses program",
             "for": "Made to each worker's prescription, usually through an optical program."},
        ],
        "questions": [
            {"id": "g_hazard", "kind": "choice", "options": ["Flying particles", "Dust", "Chemical splash",
                                                             "Welding or cutting", "A mix"],
             "text": "What's the main hazard?", "why": "Decides glasses versus goggles, and the certification."},
            {"id": "g_conditions", "kind": "choice", "options": ["Indoors", "Outdoors (glare)",
                                                                 "Cold or humid (fogging)", "Mixed"],
             "text": "What are the conditions?", "why": "Decides lens tint and anti-fog coating."},
        ],
        "checklist": [
            "Certified to CSA Z94.3 (the Canadian standard for eye and face protectors) for your hazard.",
            "Anti-fog coating for cold or humid work; anti-scratch for dusty work.",
            "Lens tint: clear indoors; tinted or indoor/outdoor lenses for glare.",
            "Fit and sizes, and comfort with hard hats and hearing protection.",
            "Box or bulk pricing, and replacement parts or cases.",
        ],
        "hazard": "Welding and cutting need shaded eye and face protection, not ordinary safety glasses.",
    },
]

for _g in GUIDES:
    _g["_broad"] = re.compile(r"^\s*(?:" + _g["broad"] + r")\s*$", re.I)
    _g["_match"] = re.compile(_g["match"], re.I)


def match(query: str) -> tuple[dict[str, Any], bool] | None:
    """(guide, broad) for a query: broad when the query is just the general term ("radios")."""
    q = (query or "").strip()
    for g in GUIDES:
        if g["_broad"].match(q):
            return g, True
        if g["_match"].search(q):
            return g, False
    return None


def consumer_words(query: str, text: str) -> str | None:
    """Words showing a listing is a consumer product ("Camping"), for a guide that defines them."""
    found = match(query)
    if not found or not found[0].get("consumer"):
        return None
    m = re.search(found[0]["consumer"], text or "", re.I)
    return m.group(0) if m else None


def public(query: str) -> dict[str, Any] | None:
    """The guide as shown to the user, or None."""
    found = match(query)
    if not found:
        return None
    g, broad = found
    return {"key": g["key"], "title": g["title"], "broad": broad, "intro": g["intro"], "types": g["types"],
            "checklist": g["checklist"], "hazard": g["hazard"], "label": LABEL}


def questions(query: str) -> list[dict[str, Any]]:
    found = match(query)
    if not found:
        return []
    return [{"placeholder": "", "options": [], **q} for q in found[0]["questions"]]


def requirements(query: str, answers: dict[str, Any] | None) -> list[str]:
    """Answers to the guide's questions, as lines for quote requests ("Used: Outdoor yard / dock")."""
    answers = answers or {}
    out = []
    for q in questions(query):
        v = answers.get(q["id"])
        if v in (None, "", "Not sure") or (q["id"] == "g_hazardous" and v == "No"):
            continue
        label = {"g_current": "Must work with current radios", "g_where": "Where used", "g_power": "Power",
                 "g_tools": "Will run", "g_duty": "Running time", "g_hazard": "Main hazard",
                 "g_conditions": "Conditions", "g_hazardous": "Classified hazardous area"}.get(q["id"], q["text"])
        out.append(f"{label}: {v}" + (" - certification for the area's classification required" if
                                      q["id"] == "g_hazardous" else ""))
    return out
