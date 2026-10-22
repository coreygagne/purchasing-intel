"""Deterministic evidence extraction from text and HTML.

Everything here only *reads* what a source says. Nothing is guessed: if a
value cannot be found it is returned as None and reported as missing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

# --------------------------------------------------------------------- input


URL_RE = re.compile(r"^\s*https?://\S+\s*$", re.I)

_UNIT_SUFFIX = (
    r"(?:v|vac|vdc|kv|volt|volts|mcm|kcmil|ft|feet|in|inch|inches|mm|cm|m|km|lb|lbs|kg|g|oz|gal|l|ml|w|kw|"
    r"kva|a|ah|amp|amps|psi|bar|hp|rpm|pack|pk|pc|pcs|ct|mah|gauge|ga|awg|mil|tpi|cfm|gpm|btu|"
    r"x|nm|k|s|st|nd|rd|th|yr|yrs|year|years|mo|day|days|deg|f|c|mp|gb|tb|mb|hz|khz|mhz|ghz|"
    r"mpa|kpa|t|ton|tons|qt|pt|sqft|cu|cuft|lm|db|ohm|mph)"
)
_UNIT_TOKEN_RE = re.compile(rf"^\d+(?:[.,]\d+)?{_UNIT_SUFFIX}$", re.I)
# Unit words that make a bare number a spec value ("1500 watt", "1000 ft-lb"). Deliberately no single
# letters, "in", "pack" or "series": "3M 6200 L", "Makita 9557 in stock", "8210 pack of 20" are models.
_SPEC_AFTER_RE = re.compile(
    r"\s*-?\s*(?:watts?|volts?|amps?|ft[- .]?lbs?|in[- .]?lbs?|feet|foot|inch(?:es)?|\"|mm|cm|lbs?|pounds?|kg|"
    r"gauge|awg|gallons?|gal|psi|btu|rpm|cfm|gpm|hp|mah|ml|litres?|liters?|oz|count|ct|pcs|pieces|sq\.? ?ft|"
    r"lumens?|degrees?|°|grit|tpi|kw|kva|hz)\b",
    re.I,
)
# cable type designations ("TECK90", "NMD90", "ACWU90", "RW90"): a kind of cable, not one product's model number
_CABLE_TYPE_RE = re.compile(r"^(?:teck|nmd|nmwu|acwu|ac|rw|rwu|tw|twu|tw75|t|xhhw|thhn|thwn|sjoow|soow|loomex)-?\d{2}$",
                            re.I)
_DIM_TOKEN_RE = re.compile(r"^\d+(?:\.\d+)?x\d+(?:\.\d+)?(?:x\d+(?:\.\d+)?)?[a-z]*$", re.I)


def classify_input(text: str) -> str:
    """Return 'url', 'model' (contains a model/part number) or 'text'."""
    if URL_RE.match(text):
        return "url"
    return "model" if model_tokens(text) else "text"


def normalize_query(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def model_tokens(text: str) -> list[str]:
    """Find likely model / part numbers (e.g. 2767-20, DCF887B, 8210).

    Conservative on purpose: units (18V, 50ft), fractions (1/2) and short
    tokens (M18, N95) are not treated as model identifiers.
    """
    found: list[str] = []
    for m in re.finditer(r"[A-Za-z0-9][A-Za-z0-9\-./]*[A-Za-z0-9]", text):
        tok = m.group(0).strip(".-/")
        if "/" in tok or len(tok) < 4:
            continue
        if tok.isdigit() and _SPEC_AFTER_RE.match(text[m.end():]):
            continue  # "1500 watt", "1000 ft-lb": a spec value, not a model number
        if re.fullmatch(r"(?:19|20)\d\d", tok):  # a year
            continue
        digits = sum(ch.isdigit() for ch in tok)
        letters = sum(ch.isalpha() for ch in tok)
        if digits == 0:
            continue
        if _UNIT_TOKEN_RE.match(tok) or _DIM_TOKEN_RE.match(tok) or _CABLE_TYPE_RE.match(tok):
            continue
        if letters == 0 and "-" not in tok and digits < 4:
            continue
        if letters > 0 and digits < 2:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", tok) and "." in tok:
            continue
        if tok.lower() not in (t.lower() for t in found):
            found.append(tok)
    return found


def product_key_for(identity_name: str, tokens: list[str]) -> str:
    """Stable key used to group price observations over time."""
    if tokens:
        return "model:" + "|".join(sorted(re.sub(r"[^a-z0-9]", "", t.lower()) for t in tokens))
    return "query:" + re.sub(r"[^a-z0-9]+", " ", identity_name.lower()).strip()


def words_from_url(url: str) -> str:
    """Readable words from a product URL's path (used only if the page can't be read)."""
    path = unquote(urlparse(url).path)
    parts = [p for p in re.split(r"[/_\-+.]", path) if p and not re.fullmatch(r"\d{6,}|html?|php|aspx?|p|dp|product|products|item|ip", p, re.I)]
    return " ".join(parts)[:150]


# --------------------------------------------------------------------- match


@dataclass
class MatchResult:
    level: str  # exact | variant | different | unverified
    notes: list[str] = field(default_factory=list)


COMPAT_RE = re.compile(r"\b(aftermarket|knock[- ]?off|replica|non[- ]oem|generic replacement)\b", re.I)
# A phrase that points at the requested model: "replacement for (Milwaukee) 2767-20", "fits DCF887B"
_PART_NOUNS = (r"batter(?:y|ies)|anvils?|chargers?|cases?|covers?|bits?|blades?|filters?|cartridges?|parts?|"
               r"accessor(?:y|ies)|adapters?|holsters?|clips?|belts?|straps?|pads?|brush(?:es)?|seals?|gaskets?|"
               r"o-rings?|kits?|motors?|switch(?:es)?|housings?|guards?|handles?|hoses?|nozzles?|tips?|refills?|"
               r"inserts?|cords?|cables?|lens(?:es)?|bulbs?|sleeves?|boots?|springs?|gears?|rotors?|brushes")
COMPAT_BEFORE_RE = re.compile(
    r"\b(compatible with|replacement for|replaces|fits|for use with|equivalent to|alternative to|substitute for|"
    r"works with|(?:" + _PART_NOUNS + r")\s+for)\s+(?:[a-z0-9&'.\-]+\s+){0,2}$",
    re.I,
)


# "...2767-20 compatible", "TX4400-replacement"
COMPAT_AFTER_RE = re.compile(r"\s*-?\s*(compatible|replacement|equivalent)\b", re.I)


def _token_regex(tok: str) -> re.Pattern[str]:
    parts = [p for p in re.split(r"[^a-z0-9]+", tok.lower()) if p]
    return re.compile(r"(?<![a-z0-9])" + r"[\s\-_./]?".join(re.escape(p) for p in parts) + r"(?![a-z0-9])", re.I)


def _compat_phrase(tokens: list[str], text: str) -> str | None:
    strong = COMPAT_RE.search(text)
    if strong:
        return strong.group(0)
    low = text.lower()
    for tok in tokens:
        for m in _token_regex(tok).finditer(low):
            c = COMPAT_BEFORE_RE.search(low[max(0, m.start() - 60): m.start()])
            if c:
                return c.group(1) + " " + tok
            after = COMPAT_AFTER_RE.match(low[m.end(): m.end() + 30])
            if after:
                return f"{tok} {after.group(1)}"
    return None


def _norm_text(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", text.lower()) + " "


def _split_model(token: str) -> tuple[str, str | None]:
    t = token.lower()
    if "-" in t:
        base, _, suffix = t.partition("-")
        return re.sub(r"[^a-z0-9]", "", base), re.sub(r"[^a-z0-9]", "", suffix) or None
    m = re.fullmatch(r"([a-z]*\d+)([a-z]+\d*)", re.sub(r"[^a-z0-9]", "", t))
    if m:
        return m.group(1), m.group(2)
    return re.sub(r"[^a-z0-9]", "", t), None


def alternative_models(request: str, tokens: list[str]) -> bool:
    """True when the request names model numbers as alternatives ("f250 or f350", "F250/F350"): a listing
    naming any one of them is the item asked for."""
    if len(tokens) < 2:
        return False
    low = (request or "").lower()
    return any(re.search(re.escape(a.lower()) + r"\s*(?:\bor\b|/|,)\s*" + re.escape(b.lower()), low)
               for a, b in zip(tokens, tokens[1:]))


def match_offer(target_tokens: list[str], offer_text: str, any_of: bool = False) -> MatchResult:
    """Compare an offer's text with the requested model numbers. `any_of`: the request names them as
    alternatives, so naming one is enough."""
    if not target_tokens:
        return MatchResult("unverified", ["No model number in the request - equivalence must be checked against specs."])
    text = _norm_text(offer_text)
    exact, variants, missing = [], [], []
    for tok in target_tokens:
        base, suffix = _split_model(tok)
        full = re.sub(r"[^a-z0-9]", "", tok.lower())
        parts = [p for p in re.split(r"[^a-z0-9]+", tok.lower()) if p]
        if len(parts) == 1 and suffix:
            parts = [base, suffix]
        pattern = r"\s" + r"\s?".join(re.escape(p) for p in parts) + r"\s"
        # letters and digits may be split in the listing: "f250" is written "F-250" or "F 250"
        runs = r"\s" + r"\s?".join(re.escape(p) for p in re.findall(r"[a-z]+|\d+", full)) + r"\s"
        if re.search(pattern, text) or re.search(runs, text) or (len(full) >= 6 and f" {full} " in text):
            exact.append(tok)
            continue
        # base found with a different suffix -> a different kit / variant
        if len(base) >= 3:
            sep = r"\s?" if suffix is not None else ""
            m = re.search(rf"\s{re.escape(base)}{sep}([a-z0-9]{{1,6}})\s", text)
            if m and m.group(1) != suffix:
                shown = f"{base.upper()}-{m.group(1).upper()}" if suffix is not None else f"{base.upper()}{m.group(1).upper()}"
                variants.append(f"{tok} requested; listing shows {shown}")
                continue
            if suffix is not None and re.search(rf"\s{re.escape(base)}\s", text):
                variants.append(f"Base model {base.upper()} found but suffix '{suffix.upper()}' not confirmed")
                continue
        missing.append(tok)
    if any_of and exact:
        missing, variants = [], []  # one of the alternatives asked for is enough
    if exact and not variants and not missing:
        compat = _compat_phrase(exact, offer_text)
        if compat:
            return MatchResult("compatible", [f"Listing mentions the model but says '{compat}' - likely a "
                                              "compatible/aftermarket item or accessory, not the original."])
        return MatchResult("exact", [f"Model {', '.join(exact)} appears in the listing."])
    if variants:
        return MatchResult("variant", variants + ([f"Not found: {', '.join(missing)}"] if missing else []))
    if exact and missing:
        return MatchResult("variant", [f"Matched {', '.join(exact)} but not {', '.join(missing)}."])
    return MatchResult("different", [f"Requested model {', '.join(target_tokens)} not found in listing text."])


CONDITION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("refurbished", re.compile(r"\b(refurbished|renewed|reconditioned|remanufactured|recertified|factory[- ]reconditioned)\b", re.I)),
    ("used", re.compile(r"(^\s*used\b|\bused\s*$|[(\[]\s*used\s*[)\]]|\bused\s*[-–:|]|\bused (?:condition|item|unit)\b|"
                        r"\bcondition:?\s*used\b|\bpre[- ]owned\b|\bsecond[- ]hand\b|\bfor parts\b)", re.I)),
    ("open box", re.compile(r"\bopen[- ]box\b", re.I)),
]


# For vehicles, machinery, classifieds and auctions the condition is usually in the ad text, not the title:
# "USED Hyster 5,000 lb", "2019 Used Crown", "Pre-Owned", an odometer reading or machine hours
_USED_WORD = re.compile(r"\bpre-?owned\b|\bused\b(?!\s+(?:by|for|to|in|with|on|as|at|daily|everyday|once)\b)", re.I)
_MILEAGE = re.compile(r"\b\d{1,3}(?:,\d{3})+\s?(?:km|kms|kilometres|kilometers|miles)\b|\b\d{4,7}\s?(?:km|kms)\b", re.I)
_HOURS = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d{3,6})\s?(?:hours|hrs)\b(?!\s+(?:a|per)\s+(?:day|week))", re.I)


_ODOMETER = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d{1,7})\s?(km|kms|kilometres|kilometers|miles|mi)\b", re.I)


def odometer_km(text: str) -> int | None:
    """Kilometres a listing states ("161,420 km", "98,000 miles" -> km), or None."""
    m = _ODOMETER.search(text or "")
    if not m:
        return None
    n = int(m.group(1).replace(",", ""))
    return round(n * 1.609344) if m.group(2).lower() in ("miles", "mi") else n


def machine_hours(text: str) -> int | None:
    """Engine or machine hours a listing states ("5806 Hours", "2,100 hrs"), or None."""
    m = _HOURS.search(text or "")
    return int(m.group(1).replace(",", "")) if m else None


def used_evidence(text: str, machinery: bool = False) -> str | None:
    """The words in an ad that show it is used ("Used", "Pre-Owned", "161,420 km", "5806 Hours"), or None."""
    for rx in (_USED_WORD, _MILEAGE) + ((_HOURS,) if machinery else ()):
        m = rx.search(text or "")
        if m:
            return m.group(0)
    return None


_YEAR = re.compile(r"(?<![\w$.,/-])((?:19[89]|20[0-4])\d)(?![\w-]|[.,]\d|\s?(?:km|kms|miles|hours|hrs|lbs?|kg)\b)",
                   re.I)


def model_years(text: str) -> list[int]:
    """Model years written in a vehicle or equipment title ("2019 Ford F-150", "Ford 2018 F-150 4x4")."""
    return sorted({int(y) for y in _YEAR.findall(text or "")})


def requested_model_year(text: str) -> int | None:
    """The one model year a request names ("2019 Ford F-150 pickup"); None when it names none or several."""
    years = model_years(text)
    return years[0] if len(years) == 1 else None


# Parts and accessories sold "for" a vehicle: in a vehicle search they mention the model but aren't the vehicle
_VEHICLE_PART = re.compile(
    r"\b(?:lift|leveling|levelling|suspension|lowering) (?:kit|system)s?\b|\bkits?\b|\bbumpers?\b|\bfender|\bflares?\b|"
    r"\bsuspension\b|\bshocks?\b|\bstruts?\b|\b(?:radius|control) arms?\b|\bbushings?\b|\bgrilles?\b|\bheadlights?\b|"
    r"\btail ?lights?\b|\blight bars?\b|\bbulbs?\b|\bmirrors?\b|\bfloor (?:mats?|liners?)\b|\btonneau\b|\bbed covers?\b|"
    r"\bseat covers?\b|\bhitch(?:es)?\b|\bwheels?\b|\brims?\b|\btires?\b|\btyres?\b|\bexhaust\b|\btuners?\b|"
    r"\binjectors?\b|\bturbo(?:chargers?)?\b|\bfilters?\b|\bbrakes?\b|\brotors?\b|\bcalipers?\b|\bparts?\b|"
    r"\baccessor(?:y|ies)\b|\bgauges?\b|\bcluster\b|\bantennas?\b|\bdecals?\b|\bemblems?\b|\brunning boards?\b|"
    r"\bnerf bars?\b|\bwinch(?:es)?\b|\bwipers?\b|\balternators?\b|\bradiators?\b|\btailgate\b|\bgaskets?\b|"
    r"\btruck caps?\b|\bcanopy\b|\btoppers?\b|\bhydro\b|\bfrt\b|\bskyjacker\b|\brough country\b|\bbilstein\b|"
    r"\bthermostats?\b|\bwrench(?:es)?\b|\bpick-?up tools?\b|\bsensors?\b|\bpumps?\b|\bvalves?\b|\bhoses?\b|"
    r"\bbelts?\b|\bbearings?\b|\bseals?\b", re.I)
# words that don't say which vehicle or machine is wanted ("pickup trucks for sale"): everything else in a request
# without a model number ("hi-rail", "dump", "forklift", "Toyota") must appear in a listing for it to be the item
_GENERIC_WORDS = {"truck", "trucks", "pickup", "pickups", "pick", "up", "vehicle", "vehicles", "car", "cars", "van", "vans",
                  "new", "used", "for", "sale", "with", "and", "or", "the", "a", "an", "of", "4x4", "4wd", "2wd", "awd",
                  "crew", "cab", "equipment", "machine", "machines", "machinery", "unit", "units", "heavy", "duty",
                  "buy", "price", "prices", "cheap", "best", "good", "lb", "lbs", "kg", "ton", "tons", "tonne", "ft",
                  "near", "me", "local", "thunder", "bay", "ontario", "canada"}
# trade spellings of the same thing, compared with spaces and hyphens removed
_SAME_THING = {"hirail": ("hirail", "hyrail", "highrail", "railgear", "railwheel"),
               "hyrail": ("hirail", "hyrail", "highrail", "railgear", "railwheel"),
               "forklift": ("forklift", "lifttruck"), "skidsteer": ("skidsteer",),
               "telehandler": ("telehandler", "telescopichandler"), "reachstacker": ("reachstacker",)}


def _squash_alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def qualifier_words(request: str, tokens: list[str]) -> list[str]:
    """The words that say which vehicle or machine is wanted, for a request without a model number: "hi-rail
    pickup trucks" -> ["hi-rail"]. Generic words, numbers, years and units are left out."""
    toks = {_squash_alnum(t) for t in tokens}
    out = []
    for w in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", (request or "").lower()):
        sq = _squash_alnum(w)
        if (not sq or sq in _GENERIC_WORDS or sq in toks or sq.isdigit() or len(sq) < 3
                or re.fullmatch(r"\d+(?:lb|lbs|kg|ft|in|t|ton|tons|hp|v|kw|km)", sq)):
            continue
        out.append(w)
    return list(dict.fromkeys(out))


def missing_qualifiers(text: str, words: list[str]) -> list[str]:
    """Which of the request's defining words a listing's text doesn't mention (trade spellings count)."""
    sq = _squash_alnum(text)
    missing = []
    for w in words:
        stem = _squash_alnum(w)
        stem = stem[:-1] if stem.endswith("s") and len(stem) > 4 else stem
        if not any(f in sq for f in _SAME_THING.get(stem, (stem,))):
            missing.append(w)
    return missing


_RENTAL = re.compile(r"\brentals?\b|\bfor rent\b|\bper (?:day|week|month)\b|/(?:day|week|month)\b|"
                     r"\b(?:daily|weekly|monthly) rates?\b|\bfor lease\b|\blease (?:from|for|rate)\b", re.I)
# an article or post on a site, not a listing: "Custom Truck makes Canadian acquisition - International Rental News"
_ARTICLE = re.compile(r"^\W*build an? \b|\bblog\b|\bwhy (?:the|you|we)\b|\bhow to\b|\breviews?\b|\bvs\.?\b|"
                      r"\bnews\b|\bacquisitions?\b|\bacquir(?:es|ed|ing)\b|\bannounces?\b|\bpress release\b|\?\s*$",
                      re.I)


def rental_words(text: str) -> str | None:
    """The words showing a listing is a rental or lease rate, not a sale price ("Rentals", "/day"), or None."""
    m = _RENTAL.search(text or "")
    return m.group(0) if m else None


def article_words(title: str) -> str | None:
    """The words showing a page is an article or post, not a listing ("News", "Blog", "Why the ..."), or None."""
    m = _ARTICLE.search(title or "")
    return m.group(0) if m else None


# toys and scale models of a vehicle: "Greenlight ... 1:64 Diecast", "Matchbox 2017 Ford F-350"
_VEHICLE_TOY = re.compile(r"\bdie-?cast\b|\b1\s?:\s?\d{2,3}\b|\bscale model\b|\bmatchbox\b|\bhot wheels\b|\bgreenlight\b|"
                          r"\btoys?\b|\breplica\b|\bmodel kit\b|\blego\b|\bremote control\b|\brc (?:car|truck)\b|"
                          r"\bmaisto\b|\bbburago\b|\bjada\b|\bm2 machines\b|\bauto world\b|\bornament\b", re.I)
# a whole vehicle's ad: starts with one model year, or states mileage, or says it's for sale
_VEHICLE_AD = re.compile(r"^\W*(?:19|20)\d\d\b(?!\s*[-–/]\s*(?:19|20)?\d\d)|\b\d[\d,]*\s?(?:km|kms|miles)\b|"
                         r"\bfor sale\b|\b(?:crew|super) ?cab\b|\bsupercrew\b", re.I)


_MODEL_TRAIN = re.compile(r"\b(?:HO|N|O|S|G)\b(?= scale| gauge| Ford| Chevy| GMC| Dodge)|\bHO\b")  # case matters: HO scale


def vehicle_toy(title: str) -> str | None:
    """The words showing a listing is a toy or scale model of a vehicle ("1:64", "Diecast", "Matchbox", "HO"),
    or None."""
    m = _VEHICLE_TOY.search(title or "") or _MODEL_TRAIN.search(title or "")
    return m.group(0) if m else None


# a part or lot of parts even when it says "for sale": "Quantity of (2) Ford Pickup Hi-Rail Axles for Sale"
_STRONG_PART = re.compile(r"\baxles?\b|^\W*(?:quantity|qty|lot) of\b|\bparts? only\b|\brail gear only\b", re.I)


def vehicle_part(title: str) -> str | None:
    """The words showing a listing is a part or accessory for a vehicle ("lift kit", "bumper"), or None."""
    strong = _STRONG_PART.search(title or "")
    if strong:
        return strong.group(0)
    m = _VEHICLE_PART.search(title or "")
    if not m or _VEHICLE_AD.search(title or ""):
        return None
    return m.group(0)


def detect_condition(text: str) -> str | None:
    for label, pat in CONDITION_PATTERNS:
        if pat.search(text):
            return label
    return None


def condition_from_schema(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.lower()
    if "new" in v:
        return "new"
    if "refurb" in v:
        return "refurbished"
    if "used" in v:
        return "used"
    if "damaged" in v:
        return "damaged"
    return None


# --------------------------------------------------------------------- price

_CURRENCY_PREFIX = {
    "ca$": "CAD", "c$": "CAD", "cdn$": "CAD", "cad$": "CAD", "cad": "CAD",
    "us$": "USD", "usd$": "USD", "usd": "USD",
    "au$": "AUD", "a$": "AUD", "nz$": "NZD", "hk$": "HKD", "s$": "SGD",
    "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP", "¥": "CNY", "cny": "CNY", "rmb": "CNY",
    "mx$": "MXN", "mxn": "MXN",
}
_SUFFIX_CODES = {"CAD", "USD", "EUR", "GBP", "CNY", "RMB", "AUD", "MXN", "JPY"}

# 1.299,99 (European) | 1,299.99 | 12,99 (decimal comma) | 349.99
_AMOUNT = (r"\d{1,3}(?:\.\d{3})+,\d{1,2}(?!\d)|\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+,\d{1,2}(?![\d,])|"
           r"\d+(?:\.\d{1,2})?")
PRICE_RE = re.compile(
    r"(?P<prefix>CA\s?\$|C\s?\$|CDN\s?\$|CAD\s?\$|US\s?\$|USD\s?\$|AU\$|A\$|NZ\$|HK\$|S\$|MX\$|\$|€|£|¥|"
    r"\b(?:CAD|USD|EUR|GBP|CNY|RMB|MXN)\s)"
    r"\s?(?P<amount>" + _AMOUNT + r")"
    r"(?:\s?\(?(?P<suffix>CAD|USD|EUR|GBP|CNY|AUD|MXN)\b\)?)?"  # "$279.00 USD", "$279.00 (USD)"
    r"(?:\s?(?:-|–|to)\s?(?:CA\$|C\$|US\$|\$|€|£|¥)?\s?(?P<high>" + _AMOUNT + r"))?",
    re.I,
)
SUFFIX_PRICE_RE = re.compile(
    r"(?<![\w.,])(?P<amount>" + _AMOUNT + r")\s?(?P<suffix>CAD|USD|EUR|GBP|CNY|RMB|AUD|MXN)\b"
)

_NOISE_BEFORE = re.compile(
    r"(save|saving|savings|off|over|under|orders?|rebate|credit|gift|coupon|reward|bonus|shipping on|"
    r"spend|minimum|min\.|up to|starting fee|deposit|from as low as|financ|/mo|per month|was|reg\.?|regular|msrp|list|"
    r"retail price|(?:regular|reg\.?|list|original|was|compare[ -]at|msrp)\s+price|approximately|approx\.?|about|"
    r"~|\+)\s*[:]?\s*$",
    re.I,
)
# a price followed by these words is a fee or saving, not the item's price ("+ $20.00 shipping")
_NOISE_AFTER = re.compile(r"^\s*(off\b|rebate|in savings|gift card|/mo|per month|a month|monthly|instant savings|or more|"
                          r"\+ shipping on orders|shipping\b|delivery fee|s&h|handling)", re.I)


@dataclass
class PriceMatch:
    amount: float
    currency: str | None  # ISO code, or None when only an ambiguous "$" was shown
    symbol: str
    raw: str
    high: float | None = None  # set when the text gives a range
    start: int = -1            # position in the text it was found in
    end: int = -1
    per: "LengthUnit | None" = None  # set when the price is quoted per foot / metre ("$76.50 / ft")

    @property
    def is_range(self) -> bool:
        return self.high is not None


def _to_float(s: str) -> float | None:
    """Parse 1,299.99 / 1.299,99 / 12,99 / 349.99. Returns None if the format is ambiguous."""
    s = (s or "").strip().replace(" ", "").replace("\u00a0", "")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{1,2}", s):        # 1.299,99
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):       # 1,299.99
        s = s.replace(",", "")
    elif re.fullmatch(r"\d+,\d{1,2}", s):                          # 12,99
        s = s.replace(",", ".")
    elif not re.fullmatch(r"\d+(?:\.\d+)?", s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


_CONTINUES_RE = re.compile(r"^[.,]?\d")
_BETWEEN_BEFORE = re.compile(r"\bbetween\s*$", re.I)
_AND_HIGH = re.compile(r"\s+and\s+(?:CA\$|C\$|US\$|\$|€|£|¥)?\s?(?P<high>" + _AMOUNT + r")(?![\d.,]?\d)", re.I)


def find_prices(text: str) -> list[PriceMatch]:
    """All plausible product prices in `text`, skipping discounts/thresholds."""
    out: list[PriceMatch] = []
    if not text:
        return out
    taken: list[tuple[int, int]] = []
    for m in PRICE_RE.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue  # the high end of a range already read
        before = text[max(0, m.start() - 25): m.start()]
        after = text[m.end(): m.end() + 25]
        if _NOISE_BEFORE.search(before) or _NOISE_AFTER.match(after):
            continue
        end = m.end()
        if _CONTINUES_RE.match(text[m.end("amount"):]):
            # number continues in a format we can't read reliably - don't guess, unless it's a
            # per-length price with 3-4 decimals ("$101.7887 / m")
            ext = _LONG_DECIMAL.match(text, m.start("amount"))
            if not (ext and length_unit_after(text, ext.end())):
                continue
            amount, end = float(ext.group(0)), ext.end()
        else:
            amount = _to_float(m.group("amount"))
        if amount is None or amount <= 0:
            continue
        prefix = m.group("prefix").strip().lower().replace(" ", "")
        suffix = (m.group("suffix") or "").upper()
        currency = _CURRENCY_PREFIX.get(prefix)
        if suffix:
            currency = "CNY" if suffix == "RMB" else suffix
        high = _to_float(m.group("high")) if m.group("high") and end == m.end() else None
        if high is None and _BETWEEN_BEFORE.search(before):
            # "value ranges between $13176 and $33686": a range, not a price
            nxt = _AND_HIGH.match(text, end)
            if nxt:
                high, end = _to_float(nxt.group("high")), nxt.end()
        if high is not None and high <= amount:
            high = None
        out.append(PriceMatch(amount, currency, m.group("prefix").strip(), text[m.start():end].strip(), high,
                              m.start(), end, per=price_length_unit(text, m.start(), end)))
        taken.append((m.start(), end))
    for m in SUFFIX_PRICE_RE.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        before = text[max(0, m.start() - 25): m.start()]
        if _NOISE_BEFORE.search(before):
            continue
        amount = _to_float(m.group("amount"))
        if amount is None or amount <= 0:
            continue
        code = m.group("suffix").upper()
        out.append(PriceMatch(amount, "CNY" if code == "RMB" else code, code, m.group(0).strip(),
                              start=m.start(), end=m.end(), per=price_length_unit(text, m.start(), m.end())))
    return sorted(out, key=lambda p: p.start)


_COMPARATIVE_BEFORE = re.compile(r"\b(than|vs\.?|versus|compared(?: to| with)?|my|his|her|their|paid|spent|"
                                 r"cost me|worth|saved|nearly|almost|pricey|hefty)\b[^$\d]{0,12}$", re.I)
_PRICE_CUE_BEFORE = re.compile(r"(price|now|sale|our|your|only|buy|cost|for|at|each|from|\bea\b|:)\s*[^\s$]{0,12}\s*$",
                               re.I)


def listing_prices(text: str, tokens: list[str]) -> list[PriceMatch]:
    """Prices in a search snippet that plausibly belong to the listed item.

    Drops prices in comparisons or anecdotes ("more torque than my $800 Snap On"). With model numbers in
    the request, keeps a price when the model is named within 150 characters before it (no other price in
    between) or a price cue precedes it ("Price:", "Your Price", "now"). Without model numbers, only the
    comparison filter applies."""
    out = []
    for p in find_prices(text):
        before = text[max(0, p.start - 40): p.start]
        if _COMPARATIVE_BEFORE.search(before):
            continue
        if not tokens:
            out.append(p)
            continue
        cue = bool(_PRICE_CUE_BEFORE.search(before))
        near = False
        window_start = max(0, p.start - 150)
        low = text.lower()
        for tok in tokens:
            mentions = list(_token_regex(tok).finditer(low, window_start, p.start))
            if mentions and not find_prices(text[mentions[-1].end(): p.start]):
                near = True
                break
        if cue or near:
            out.append(p)
    return out


def parse_price_text(text: str) -> PriceMatch | None:
    """Parse a short price string such as '$349.00' or 'CA$1,299.99'."""
    found = find_prices(text)
    if found:
        return found[0]
    # bare number (e.g. a JSON-LD "price": "349.00")
    m = re.fullmatch(r"\s*(" + _AMOUNT + r")\s*", text or "")
    if m:
        v = _to_float(m.group(1))
        if v is not None:
            return PriceMatch(v, None, "", text.strip())
    return None


QUOTE_RE = re.compile(
    r"request (?:a )?quote|call for pric|contact (?:us )?for (?:a )?(?:pric|quote)|price on request|"
    r"pricing (?:available )?(?:up)?on request|(?:log ?in|sign ?in) (?:to|for) (?:see |view )?(?:your )?pric|"
    r"\bRFQ\b|get a quote|request pricing|quote required|call for quote|ask for (?:a )?quote",
    re.I,
)


def quote_required(text: str) -> str | None:
    m = QUOTE_RE.search(text or "")
    return m.group(0) if m else None


PACK_PATTERNS = [
    re.compile(r"\b(?:pack|box|case|bag|carton|bundle|set|lot|pail|tub|roll)\s+of\s+(\d{1,5})\b", re.I),
    re.compile(r"\b(\d{1,5})\s?(?:-|\s)?(?:pack|pk|pkg|pcs|pieces|count|ct|per box|per case|/box|/case|/pk|/pack|/bag)\b", re.I),
    re.compile(r"\((\d{1,5})\s?(?:pk|pack|pcs|ct|count)\)", re.I),
    # "100 Gloves/Box", "Extra Large100/bx", "12/cs", "200 pcs/case"
    re.compile(r"(?<!\d)(\d{1,5})\s?(?:[a-z]+\s?)?/\s?(?:box|bx|cs|case|ctn|carton|pk|pack|bag|bg)\b", re.I),
    re.compile(r"\bqty[:\s]+(\d{1,5})\b", re.I),
]


_SET_RE = re.compile(r"\b(set|kit|assortment|assorted|organizer|collection|combo)\b", re.I)


def pack_quantity(text: str) -> tuple[int, str] | None:
    """Units per listing if the listing states a pack/box/case size."""
    is_set = bool(_SET_RE.search(text or ""))
    for pat in PACK_PATTERNS:
        for m in pat.finditer(text or ""):
            before = (text or "")[max(0, m.start() - 30): m.start()].lower()
            if re.search(r"order|moq|min\.?|minimum|at least|up to|max", before):
                continue  # an order quantity, not a pack size
            if is_set and re.search(r"pcs|pieces", m.group(0), re.I):
                continue  # "Socket set (28 pcs)": pieces in one item; "kit refill, 100 count" stays a pack
            qty = int(m.group(1))
            if 1 < qty <= 100000:
                return qty, m.group(0)
    return None


MOQ_RE = re.compile(
    r"(?:\bMOQ\b|min(?:imum)?\.?\s*order(?:\s*(?:quantity|qty))?)\s*[:：]?\s*(?:is\s*)?(\d[\d,]*)\s*([A-Za-z]+)?",
    re.I,
)


def moq_text(text: str) -> str | None:
    m = MOQ_RE.search(text or "")
    return m.group(0).strip() if m else None


WARRANTY_RE = re.compile(
    r"(?:limited\s+)?lifetime\s+(?:limited\s+)?warranty|"
    r"\b(?:\d{1,2}|one|two|three|four|five|six|seven|ten)[-\s]?(?:year|yr|month|mo|day)s?\s+(?:limited\s+|manufacturer'?s?\s+|parts\s+(?:and|&)\s+labou?r\s+)?warranty|"
    r"warranty\s*[:\-]\s*(?:\d{1,2}|one|two|three|five|ten)\s*(?:year|yr|month|day)s?",
    re.I,
)


def warranty_text(text: str) -> str | None:
    m = WARRANTY_RE.search(text or "")
    return m.group(0).strip() if m else None


SHIPPING_RE = re.compile(
    r"free (?:standard |ground )?(?:shipping|delivery)(?: on (?:orders|purchases) (?:over|of) \$?\d+(?:\.\d\d)?\+?)?|"
    r"ships? (?:in|within) \d+(?:\s?-\s?\d+)? (?:business )?(?:days?|weeks?)|"
    r"(?:delivery|delivered) (?:in|within) \d+(?:\s?-\s?\d+)? (?:business )?(?:days?|weeks?)|"
    r"(?:shipping|delivery)\s*[:]\s*(?:CA)?\$\d+(?:\.\d\d)?|"
    r"\+\s?(?:CA?\s?|US\s?)?\$\s?\d+(?:\.\d\d)?\s+(?:shipping|delivery)",
    re.I,
)


def shipping_text(text: str) -> str | None:
    m = SHIPPING_RE.search(text or "")
    return m.group(0).strip() if m else None


def shipping_cost_from_text(text: str | None) -> float | None:
    """Only returns a number when the text states it unambiguously."""
    if not text:
        return None
    t = text.lower()
    if t.startswith("free") and "over" not in t and " of " not in t:
        return 0.0
    m = re.search(r"(?:shipping|delivery)\s*[:]\s*(?:ca)?\$(\d+(?:\.\d\d)?)", t) or \
        re.search(r"\+\s?(?:ca?\s?|us\s?)?\$\s?(\d+(?:\.\d\d)?)\s+(?:shipping|delivery)", t)
    if m:
        return float(m.group(1))
    return None


AVAIL_RE = re.compile(r"\b(in stock|out of stock|sold out|backorder(?:ed)?|special order|discontinued|pre-?order|"
                      r"limited stock|currently unavailable|unavailable|no longer available|not available)\b", re.I)


def availability_text(text: str) -> str | None:
    m = AVAIL_RE.search(text or "")
    return m.group(0).lower() if m else None


BULK_RE = re.compile(
    r"\b(bulk pricing|volume pricing|volume discount|quantity discount|tiered pricing|wholesale(?: pricing| price)?|"
    r"case pricing|contract pricing|buy in bulk|bulk order|bulk discount)\b",
    re.I,
)


def bulk_signal(text: str) -> str | None:
    m = BULK_RE.search(text or "")
    return m.group(0) if m else None


ISSUE_RE = re.compile(
    r"\b(recall(?:ed|s)?|defect(?:ive|s)?|broke|broken|fail(?:ed|s|ure|ures)?|stopped working|overheat(?:s|ed|ing)?|"
    r"leak(?:s|ed|ing)?|crack(?:s|ed)?|return(?:ed)? it|died|dies|unreliable|poor quality|junk|safety (?:issue|hazard|notice)|"
    r"fire hazard|burn hazard|injur(?:y|ies))\b",
    re.I,
)
PRAISE_RE = re.compile(
    r"\b(reliable|durable|well[- ]built|solid|excellent|great value|highly recommend(?:ed)?|works great|"
    r"best (?:in class|value)|heavy[- ]duty|long[- ]lasting|top pick|recommended)\b",
    re.I,
)


def sentences_matching(text: str, pattern: re.Pattern[str], limit: int = 3) -> list[str]:
    """Verbatim sentences from `text` that contain `pattern`."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        s = sent.strip()
        if 20 <= len(s) <= 400 and pattern.search(s):
            out.append(s)
            if len(out) >= limit:
                break
    return out


# ------------------------------------------------------------- structured data


def _types(node: dict[str, Any]) -> set[str]:
    t = node.get("@type")
    if isinstance(t, str):
        return {t.split("/")[-1]}
    if isinstance(t, list):
        return {str(x).split("/")[-1] for x in t}
    return set()


def _walk(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def jsonld_blocks(html: str) -> list[Any]:
    soup = BeautifulSoup(html, "html.parser")
    blocks = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            blocks.append(json.loads(raw))
        except json.JSONDecodeError:
            # Some sites emit trailing commas; one conservative repair attempt.
            try:
                blocks.append(json.loads(re.sub(r",\s*([}\]])", r"\1", raw)))
            except json.JSONDecodeError:
                continue
    return blocks


def _first(v: Any) -> Any:
    return v[0] if isinstance(v, list) and v else v


def _name(v: Any) -> str | None:
    v = _first(v)
    if isinstance(v, dict):
        return v.get("name")
    return v if isinstance(v, str) else None


@dataclass
class StructuredOffer:
    price: float | None
    price_high: float | None
    currency: str | None
    availability: str | None
    condition: str | None
    seller: str | None
    url: str | None
    raw_price: str
    aggregate: bool = False  # schema.org AggregateOffer: a "from" price across several sellers/variants
    sku: str | None = None
    name: str | None = None


@dataclass
class StructuredProduct:
    name: str | None
    brand: str | None
    sku: str | None
    mpn: str | None
    gtin: str | None
    description: str | None
    offers: list[StructuredOffer]
    rating_value: float | None
    rating_count: int | None
    rating_best: float | None
    specs: dict[str, str]


def _offer_nodes(offers: Any) -> list[dict[str, Any]]:
    if isinstance(offers, dict):
        return [offers]
    if isinstance(offers, list):
        return [o for o in offers if isinstance(o, dict)]
    return []


def _parse_offer(o: dict[str, Any]) -> StructuredOffer | None:
    types = _types(o)
    spec = _first(o.get("priceSpecification")) if isinstance(o.get("priceSpecification"), (dict, list)) else None
    price_raw = o.get("price")
    if price_raw in (None, "") and isinstance(spec, dict):
        price_raw = spec.get("price")
    currency = o.get("priceCurrency") or (spec.get("priceCurrency") if isinstance(spec, dict) else None)
    low = high = None
    aggregate = "AggregateOffer" in types or ("lowPrice" in o and price_raw in (None, ""))
    if aggregate:
        low = _to_float(str(o.get("lowPrice"))) if o.get("lowPrice") not in (None, "") else None
        high = _to_float(str(o.get("highPrice"))) if o.get("highPrice") not in (None, "") else None
        if high is not None and low is not None and high <= low:
            high = None
        price = low
        raw = f"{o.get('lowPrice')}-{o.get('highPrice')}" if high else str(o.get("lowPrice"))
    else:
        price = _to_float(str(price_raw)) if price_raw not in (None, "") else None
        raw = str(price_raw) if price_raw is not None else ""
    if price is not None and price <= 0:
        price = None
    avail = o.get("availability")
    if isinstance(avail, str):
        avail = re.sub(r"^https?://schema\.org/", "", avail)
    return StructuredOffer(
        price=price,
        price_high=high,
        currency=currency.upper() if isinstance(currency, str) and len(currency) == 3 else None,
        availability=avail if isinstance(avail, str) else None,
        condition=condition_from_schema(o.get("itemCondition")),
        seller=_name(o.get("seller")),
        url=o.get("url") if isinstance(o.get("url"), str) else None,
        raw_price=raw,
        aggregate=aggregate,
        sku=str(o.get("sku")) if o.get("sku") else None,
        name=o.get("name") if isinstance(o.get("name"), str) else None,
    )


def page_image(html: str, base_url: str) -> str | None:
    """The page's main picture, for a preview: the schema.org Product image, else the Open Graph or Twitter
    card image. Only an absolute http(s) address is returned."""
    from urllib.parse import urljoin
    candidates: list[str] = []
    for block in jsonld_blocks(html):
        for node in _walk(block):
            if isinstance(node, dict) and {"Product", "ProductModel", "IndividualProduct", "Car", "Vehicle"} & _types(node):
                img = node.get("image")
                if isinstance(img, list):
                    img = img[0] if img else None
                if isinstance(img, dict):
                    img = img.get("url") or img.get("contentUrl")
                if isinstance(img, str):
                    candidates.append(img)
    soup = BeautifulSoup(html, "html.parser")
    for attrs in ({"property": "og:image"}, {"name": "og:image"}, {"name": "twitter:image"},
                  {"property": "twitter:image"}):
        tag = soup.find("meta", attrs=attrs)
        if tag is not None and tag.get("content"):
            candidates.append(str(tag["content"]))
    for c in candidates:
        url = urljoin(base_url, c.strip())
        if re.match(r"https?://[^\s\"'<>]+$", url) and len(url) <= 1000:
            return url
    return None


def structured_products(html: str) -> list[StructuredProduct]:
    """schema.org Product data (JSON-LD) plus Open Graph / microdata price fallbacks."""
    products: list[StructuredProduct] = []
    for block in jsonld_blocks(html):
        for node in _walk(block):
            if not isinstance(node, dict) or not ({"Product", "ProductModel", "IndividualProduct"} & _types(node)):
                continue
            offers = [x for x in (_parse_offer(o) for o in _offer_nodes(node.get("offers"))) if x]
            rating = node.get("aggregateRating") if isinstance(node.get("aggregateRating"), dict) else {}
            specs: dict[str, str] = {}
            for prop in node.get("additionalProperty") or []:
                if isinstance(prop, dict) and prop.get("name") and prop.get("value") not in (None, ""):
                    specs[str(prop["name"])[:80]] = str(prop["value"])[:200]
            for key in ("color", "material", "weight", "width", "height", "depth", "size", "model"):
                val = node.get(key)
                if isinstance(val, (str, int, float)):
                    specs.setdefault(key, str(val)[:200])
                elif isinstance(val, dict) and val.get("value") is not None:
                    specs.setdefault(key, f"{val.get('value')} {val.get('unitText') or val.get('unitCode') or ''}".strip())
            count = rating.get("reviewCount") or rating.get("ratingCount")
            products.append(StructuredProduct(
                name=node.get("name") if isinstance(node.get("name"), str) else None,
                brand=_name(node.get("brand")),
                sku=str(node.get("sku")) if node.get("sku") else None,
                mpn=str(node.get("mpn")) if node.get("mpn") else None,
                gtin=str(node.get("gtin13") or node.get("gtin12") or node.get("gtin") or node.get("gtin14") or "") or None,
                description=(node.get("description") or "")[:600] if isinstance(node.get("description"), str) else None,
                offers=offers,
                rating_value=_to_float(str(rating.get("ratingValue"))) if rating.get("ratingValue") not in (None, "") else None,
                rating_count=int(_to_float(str(count)) or 0) if count not in (None, "") else None,
                rating_best=_to_float(str(rating.get("bestRating"))) if rating.get("bestRating") not in (None, "") else None,
                specs=specs,
            ))
    if not any(p.offers for p in products):
        meta = _meta_price(html)
        if meta:
            products.append(meta)
    return products


def _meta_price(html: str) -> StructuredProduct | None:
    soup = BeautifulSoup(html, "html.parser")

    def meta(*names: str) -> str | None:
        for n in names:
            tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n}) \
                or soup.find(attrs={"itemprop": n})
            if tag is not None:
                val = tag.get("content") or tag.get_text(strip=True)
                if val:
                    return str(val)
        return None

    amount = meta("product:price:amount", "og:price:amount", "price")
    if not amount:
        return None
    value = _to_float(re.sub(r"[^\d.,]", "", amount))
    if value is None or value <= 0:
        return None
    currency = meta("product:price:currency", "og:price:currency", "priceCurrency")
    title = meta("og:title") or (soup.title.get_text(strip=True) if soup.title else None)
    return StructuredProduct(
        name=title, brand=meta("product:brand", "og:brand"), sku=None, mpn=None, gtin=None, description=None,
        offers=[StructuredOffer(value, None, currency.upper() if currency and len(currency) == 3 else None,
                                meta("product:availability", "og:availability"), None, None, None, amount)],
        rating_value=None, rating_count=None, rating_best=None, specs={},
    )


def page_title(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return str(og["content"]).strip()
    if soup.title:
        return soup.title.get_text(strip=True)
    return None


# ---------------------------------------------------------------- sold by length
# Cable, hose, chain and rope are often priced per foot or metre. Such prices are compared per foot, never
# against per-item prices, and a bare "/M" is left unclear: in the wire trade it can mean per 1,000 ft.

FT_PER_M = 3.28084
_LONG_DECIMAL = re.compile(r"\d+\.\d{3,4}(?!\d)")
_LEN_UNIT = (r"(?P<unit>lin(?:ear)?\.?\s*f(?:ee|oo)?t\b\.?|l\.f\.|lf\b|ft\b\.?|foot\b|feet\b|'|"
             r"lin(?:ear)?\.?\s*m(?:etres?|eters?)?\b|metres?\b|meters?\b|mtrs?\b|m\b)(?![²³^]|\d)")
_PER_LENGTH_AFTER = re.compile(r"\s*(?:/|per\s+|a\s+)\s*(?:(?P<qty>\d{1,3}(?:,\d{3})+|\d+)\s*)?"
                               r"(?P<k>[Mk](?=\s*(?:ft\b|feet\b|')))?\s*" + _LEN_UNIT, re.I)
_PER_LENGTH_BEFORE = re.compile(r"\b(?:price|cost)\s+(?:per|/)\s+(?:linear\s+)?(?P<unit>foot|ft|metre|meter|m)\b"
                                r"[^$\d]{0,12}$", re.I)
_SOLD_BY_LENGTH = re.compile(r"\b(?:sold|priced|prices?|cut)\s+(?:by|per)\s+(?:the\s+)?(?:linear\s+)?"
                             r"(?P<unit>foot|feet|ft|metre|meter)\b|\(\s*per\s+(?P<unit2>foot|ft|metre|meter)\s*\)",
                             re.I)


@dataclass
class LengthUnit:
    unit: str          # "ft" | "m" | "?" (a bare "/M": per metre or per 1,000 ft)
    qty: float = 1.0   # the price covers this many units ("per 1,000 ft" -> 1000)
    text: str = ""     # as written

    @property
    def feet(self) -> float | None:
        return self.qty if self.unit == "ft" else (self.qty * FT_PER_M if self.unit == "m" else None)

    @property
    def label(self) -> str:
        if self.unit == "?":
            return "/M (unclear)"
        n = f"{self.qty:,.0f} " if self.qty != 1 else ""
        return f"per {n}{self.unit}"


def _unit_kind(raw: str) -> str:
    low = raw.lower()
    return "ft" if ("f" in low or low == "'") else "m"


def length_unit_after(text: str, pos: int) -> LengthUnit | None:
    """The length unit a price ending at `pos` is quoted per ("/ ft", "per metre", "/1000 ft"), if any."""
    m = _PER_LENGTH_AFTER.match(text or "", pos)
    if not m:
        return None
    raw = m.group("unit")
    qty = float(m.group("qty").replace(",", "")) if m.group("qty") else 1.0
    if m.group("k"):
        qty *= 1000
    if raw == "M" and not m.group("qty"):
        return LengthUnit("?", 1.0, m.group(0).strip())
    return LengthUnit(_unit_kind(raw), qty, m.group(0).strip())


def price_length_unit(text: str, start: int, end: int) -> LengthUnit | None:
    """Per-length unit stated right after a price, or just before it ("Price per foot: $76.50")."""
    after = length_unit_after(text, end)
    if after:
        return after
    m = _PER_LENGTH_BEFORE.search(text[max(0, start - 40): start])
    return LengthUnit(_unit_kind(m.group("unit")), 1.0, m.group(0).strip()) if m else None


def sold_by_length(text: str) -> LengthUnit | None:
    """'Sold by the foot', 'priced per metre', '(per ft)' in a title or page."""
    m = _SOLD_BY_LENGTH.search(text or "")
    if not m:
        return None
    return LengthUnit(_unit_kind(m.group("unit") or m.group("unit2")), 1.0, m.group(0).strip())


_PACKAGED_LENGTH = re.compile(
    r"(?<![\w/.-])(?P<n>\d[\d,]*(?:\.\d+)?)\s*-?\s*(?P<u>ft\b\.?|feet\b|foot\b|'|m\b|metres?\b|meters?\b)\s*-?\s*"
    r"(?:reel|spool|coil|roll|drum|box|cut|length)s?\b|"
    r"\b(?:reel|spool|coil|roll|drum|box|cut)s?\s+of\s+(?P<n2>\d[\d,]*(?:\.\d+)?)\s*(?P<u2>ft\b|feet\b|foot\b|'|m\b|metres?\b|"
    r"meters?\b)", re.I)


def packaged_length(title: str) -> LengthUnit | None:
    """Length of a reel, spool or cut sold as one item ("250 ft reel", "spool of 500 m")."""
    m = _PACKAGED_LENGTH.search(title or "")
    if not m:
        return None
    n = float((m.group("n") or m.group("n2")).replace(",", ""))
    if n <= 0:
        return None
    return LengthUnit(_unit_kind(m.group("u") or m.group("u2")), n, m.group(0).strip())


def amount_length_unit(text: str, amount: float) -> LengthUnit | None:
    """Unit written after `amount` where it appears in page text ("$8.42 / ft")."""
    for shown in {f"{amount:,.2f}", f"{amount:.2f}", f"{amount:g}"}:
        for m in re.finditer(r"(?<![\d.,])" + re.escape(shown) + r"(?![\d])", text or ""):
            unit = length_unit_after(text, m.end())
            if unit:
                return unit
    return None


# ------------------------------------------------------------- requested specs
# For plain-language requests (no model number), the sizes and materials the request states are checked
# against each listing's own title and quoted text: a listing that states a different value is a different
# item; one that doesn't state it is unconfirmed.

_NUM = r"(?:\d+-\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
_ORDER_LENGTH = re.compile(r"(?<![\w/.-])(?P<n>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>ft\b\.?|feet\b|foot\b|'|m\b|metres?\b|meters?\b)"
                           r"\s+(?:of|roll|reel|spool|coil|length|cut)\b", re.I)
_KCMIL = re.compile(r"\b(\d{3,4})\s*-?\s*(?:mcm|kcmil)\b", re.I)
_AWG = re.compile(r"(?:#\s*)?\b(\d{1,2}|[1-4]/0)\s*-?\s*(?:awg|ga\b|gauge\b)|#\s*(\d{1,2}|[1-4]/0)\b(?!\s*-?\d)", re.I)
_SIZE_SLASH_C = re.compile(r"(?<![\w/.])([1-4]/0|\d{1,4})/(\d{1,2})C\b", re.I)
# "available from #14 to 500 kcmil": the sizes a product line comes in, not this listing's size
_SIZE_RANGE = re.compile(r"(?:from\s+)?#?\s?\d[\d/]*\s*(?:awg|kcmil|mcm)?\s+(?:to|through|thru)\s+#?\s?\d[\d/]*\s*"
                         r"(?:awg|kcmil|mcm)\b", re.I)
_CORD = re.compile(r"(?<![\d/.])\b(18|16|14|12|10|8|6)\s*/\s*([2-5])\b(?!\s*(?:in|inch|\"|mm))", re.I)
_MM2 = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:mm2|mm²|sq\.?\s*mm)\b", re.I)
_CONDUCTORS = re.compile(r"\b(\d{1,2})\s*-?\s*(?:conductors?\b|cond\b\.?)|\b(\d{1,2})(?:-|/|\s)?c\b(?![-.\w°])|"
                         r"\b(single|two|three|four|five|six)[\s-]+conductors?\b", re.I)
_WORD_NUM = {"single": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_COPPER = re.compile(r"\b(?:copper|cu)\b", re.I)
_ALUMINUM = re.compile(r"\b(?:alumin(?:i)?um|alum|al)\b", re.I)
_ARMOUR_CONTEXT = re.compile(r"armou?r|interlock|sheath|jacket|clad", re.I)
_UNITS = {
    "v": "V", "volt": "V", "volts": "V", "kv": "kV", "a": "A", "amp": "A", "amps": "A", "w": "W", "watt": "W",
    "watts": "W", "kw": "kW", "hp": "HP", "psi": "psi", "gal": "gal", "gallon": "gal", "gallons": "gal",
    "l": "L", "litre": "L", "litres": "L", "liter": "L", "liters": "L", "mm": "mm", "cm": "cm", "in": "in",
    "inch": "in", "inches": "in", "\"": "in", "ft": "ft", "feet": "ft", "foot": "ft", "lb": "lb", "lbs": "lb",
    "kg": "kg", "ton": "ton", "tons": "ton", "tonne": "tonne", "tonnes": "tonne", "oz": "oz",
}
_SCALE = {"kV": ("V", 1000.0), "kW": ("W", 1000.0)}
_GENERIC = re.compile(r"(?<![\w/.])(?P<n>" + _NUM + r")\s*-?\s*(?P<u>kv|kw|v|volts?|amps?|a|watts?|w|hp|psi|"
                      r"gallons?|gal|litres?|liters?|l|mm|cm|inch(?:es)?|in|\"|feet|foot|ft|lbs?|kg|tonnes?|tons?|oz)"
                      r"(?![\w²³])", re.I)


def _num(value: str) -> float | None:
    try:
        if "-" in value and "/" in value:                       # 1-1/2
            whole, frac = value.split("-", 1)
            n, d = frac.split("/")
            return float(whole) + float(n) / float(d)
        if "/" in value:
            n, d = value.split("/")
            return float(n) / float(d)
        return float(value)
    except (ValueError, ZeroDivisionError):
        return None


def _spec(dim: str, value: str, num: float | None = None, label: str | None = None) -> dict[str, Any]:
    return {"dim": dim, "value": value, "num": num, "label": label or value}


def _conductors(n: int) -> dict[str, Any]:
    return _spec("conductors", str(n), float(n), f"{n}-conductor")


def order_length(text: str) -> dict[str, Any] | None:
    """A length to buy stated in the request ("300 ft of ... cable", "150 m roll")."""
    m = _ORDER_LENGTH.search(text or "")
    if not m:
        return None
    n = float(m.group("n").replace(",", ""))
    unit = _unit_kind(m.group("unit"))
    return {"value": n, "unit": unit, "feet": n if unit == "ft" else round(n * FT_PER_M, 2),
            "text": f"{n:g} {unit}", "span": [m.start(), m.end()]}


def specs_in(text: str, *, materials: bool = True) -> list[dict[str, Any]]:
    """Sizes, conductor counts, conductor material and other number+unit specs written in `text`."""
    text = text or ""
    out: list[dict[str, Any]] = []
    used: list[tuple[int, int]] = []

    def add(m: re.Match, spec: dict[str, Any]) -> None:
        out.append(spec)
        used.append((m.start(), m.end()))

    for m in _SIZE_SLASH_C.finditer(text):  # trade catalogue style: "300/3C", "3/0/3C", "12/3C"
        size, n = m.group(1), int(m.group(2))
        if re.fullmatch(r"[1-4]/0", size):
            add(m, _spec("conductor size", f"{size} AWG"))
        elif int(size) >= 250:
            add(m, _spec("conductor size", f"{int(size)} kcmil"))
        elif int(size) <= 18:
            add(m, _spec("conductor size", f"{int(size)} AWG"))
        else:
            continue
        if 1 <= n <= 12:
            out.append(_conductors(n))
    for m in _KCMIL.finditer(text):
        if any(s <= m.start() < e for s, e in used):
            continue
        add(m, _spec("conductor size", f"{int(m.group(1))} kcmil"))
    for m in _CORD.finditer(text):
        add(m, _spec("conductor size", f"{m.group(1)} AWG"))
        out.append(_conductors(int(m.group(2))))
    for m in _AWG.finditer(text):
        if any(s <= m.start() < e for s, e in used):
            continue
        add(m, _spec("conductor size", f"{m.group(1) or m.group(2)} AWG"))
    for m in _MM2.finditer(text):
        add(m, _spec("conductor size (mm²)", f"{m.group(1)} mm²", float(m.group(1))))
    for m in _CONDUCTORS.finditer(text):
        if any(s <= m.start() < e for s, e in used):
            continue  # already read with its size ("300/3C")
        n = int(m.group(1) or m.group(2) or _WORD_NUM[m.group(3).lower()])
        if 1 <= n <= 12:
            add(m, _conductors(n))
    if materials:
        cu = bool(_COPPER.search(text))
        al = any(not _ARMOUR_CONTEXT.search(text[max(0, m.start() - 20): m.end() + 20])
                 for m in _ALUMINUM.finditer(text))
        if cu:
            out.append(_spec("conductor material", "copper"))
        if al:
            out.append(_spec("conductor material", "aluminum"))
    for m in _GENERIC.finditer(text):
        if any(s <= m.start() < e for s, e in used):
            continue
        unit = _UNITS.get(m.group("u").lower(), m.group("u"))
        num = _num(m.group("n"))
        if num is None:
            continue
        base, factor = _SCALE.get(unit, (unit, 1.0))
        out.append({"dim": base, "value": f"{m.group('n')} {unit}", "num": num * factor,
                    "label": f"{m.group('n')} {unit}"})
    return out


def request_specs(text: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """(specs to check in listings, length to buy) for a plain-language request."""
    length = order_length(text)
    body = text or ""
    if length:
        s, e = length["span"]
        body = body[:s] + " " + body[e:]
    specs = specs_in(body)
    mats = {sp["value"] for sp in specs if sp["dim"] == "conductor material"}
    if len(mats) > 1:  # "copper or aluminum": the request doesn't fix it
        specs = [sp for sp in specs if sp["dim"] != "conductor material"]
    seen, unique = set(), []
    for sp in specs:
        key = (sp["dim"], sp["value"])
        if key not in seen:
            seen.add(key)
            unique.append(sp)
    return unique, length


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.get("num") is not None and b.get("num") is not None:
        return abs(a["num"] - b["num"]) < 1e-6 * max(1.0, abs(a["num"]))
    return a["value"].lower() == b["value"].lower()


def spec_check(requested: list[dict[str, Any]], listing_text: str) -> dict[str, list[str]]:
    """Which requested specs the listing text confirms, contradicts or doesn't mention."""
    found = specs_in(_SIZE_RANGE.sub(" ", listing_text or ""))
    out: dict[str, list[str]] = {"confirmed": [], "missing": [], "conflicts": []}
    for req in requested:
        same_dim = [f for f in found if f["dim"] == req["dim"]]
        if any(_same(req, f) for f in same_dim):
            out["confirmed"].append(req["label"])
        elif same_dim:
            shown = ", ".join(dict.fromkeys(f["label"] for f in same_dim))
            out["conflicts"].append(f"listing says {shown}; you asked for {req['label']}")
        else:
            out["missing"].append(req["label"])
    return out


def page_text(html: str, limit: int = 20000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)[:limit]


def focus_text(text: str, tokens: list[str], limit: int) -> str:
    """At most `limit` characters of `text`, starting shortly before the first model-number mention that has a
    price after it (else the first mention). Pages read as plain text often open with long navigation."""
    if len(text) <= limit:
        return text
    mentions = sorted(m.start() for t in tokens for m in _token_regex(t).finditer(text))
    if not mentions:
        return text[:limit]
    priced = next((i for i in mentions if find_prices(text[i:i + 1500])), mentions[0])
    start = max(0, priced - limit // 5)
    return text[start:start + limit]


# ------------------------------------------------------------------ contacts
# Contact details are copied from the business's own page (tel:/mailto: links, schema.org business data, page
# text) or from a map/directory listing, always with where they were seen. Nothing is inferred.

_PHONE = re.compile(r"(?<![\d\w-])(?:\+?1[\s.-]?)?\(?([2-9]\d{2})\)?[\s.-]?([2-9]\d{2})[\s.-]?(\d{4})(?![\d-])"
                    r"(?:\s*(?:,\s*)?(?:ext\.?|extension|x)\s*(\d{1,6}))?", re.I)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
_POSTAL = re.compile(r"\b([ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z])[ -]?(\d[ABCEGHJ-NPRSTV-Z]\d)\b")
_US_ZIP = re.compile(r"\b(A[KLRZ]|C[AOT]|D[CE]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|"
                     r"T[NX]|UT|V[AT]|W[AIVY])\s+\d{5}(?:-\d{4})?\b")
_BAD_EMAIL_END = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")
# form placeholders ("you@example.com", "name@domain.com"), not anyone's address
_PLACEHOLDER_EMAIL = re.compile(r"@(?:example\.(?:com|org|net)|[\w-]+\.example|domain\.com|email\.com|yourdomain\.\w+)$",
                                re.I)


def _phone_fmt(m: re.Match) -> str:
    """The number as written (with its extension), only trimmed."""
    return re.sub(r"\s+", " ", m.group(0)).strip(" ,.")


def phone_key(value: str) -> str:
    """Digits identifying a phone number (for de-duplication only): area code, number and extension."""
    m = _PHONE.search(value or "")
    if not m:
        return re.sub(r"\D", "", value or "")
    return f"{m.group(1)}{m.group(2)}{m.group(3)}" + (f"x{m.group(4)}" if m.group(4) else "")


def contacts_in_text(text: str, limit: int = 3) -> dict[str, list[str]]:
    """Phone numbers, emails and postal-code addresses written in `text`."""
    text = text or ""
    phones, keys = [], set()
    for m in _PHONE.finditer(text):
        k = phone_key(m.group(0))
        if k not in keys:
            keys.add(k)
            phones.append(_phone_fmt(m))
    phones = phones[:limit]
    emails = [e for e in dict.fromkeys(m.group(0) for m in _EMAIL.finditer(text))
              if not e.lower().endswith(_BAD_EMAIL_END) and not _PLACEHOLDER_EMAIL.search(e)][:limit]
    addresses = []
    for m in _POSTAL.finditer(text):
        # the address is the street line before the postal code: from its street number, within the same
        # sentence or field ("Head office: 200 Bay St, Toronto ON M5J 2J2" -> "200 Bay St, Toronto ON M5J 2J2")
        start = max(0, m.start() - 90)
        chunk = re.sub(r"\s+", " ", text[start:m.end()])
        chunk = re.split(r"[|•·]|(?<=[a-z0-9)])[.!?:;]\s", chunk)[-1].strip(" ,")
        street = list(re.finditer(r"(?<![\w-])\d{1,6}[A-Za-z]?(?:-\d{1,5})?\s+(?=[A-Z0-9])", chunk))
        if street:
            chunk = chunk[street[0].start():]
        elif not re.search(r",", chunk):
            continue  # a postal code with no street or town before it isn't an address
        addresses.append(chunk)
    return {"phones": phones, "emails": emails, "addresses": list(dict.fromkeys(addresses))[:limit]}


def contacts_in_html(html: str) -> dict[str, list[str]]:
    """Contacts on a business's own page: tel:/mailto: links and schema.org data first, then the page text
    (including the header and footer, where contact details usually are)."""
    soup = BeautifulSoup(html or "", "html.parser")
    phones, emails, addresses = [], [], []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("tel:"):
            m = _PHONE.search(href[4:])
            if m:
                phones.append(_phone_fmt(m))
        elif href.lower().startswith("mailto:"):
            addr = href[7:].split("?")[0].strip()
            if _EMAIL.fullmatch(addr):
                emails.append(addr)
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        for node in _ld_nodes(data):
            if not isinstance(node, dict):
                continue
            tel, mail, adr = node.get("telephone"), node.get("email"), node.get("address")
            if isinstance(tel, str) and _PHONE.search(tel):
                phones.append(_phone_fmt(_PHONE.search(tel)))
            if isinstance(mail, str) and _EMAIL.search(mail):
                emails.append(_EMAIL.search(mail).group(0))
            if isinstance(adr, dict):
                parts = [adr.get(k) for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode")]
                line = ", ".join(str(x).strip() for x in parts if isinstance(x, str) and x.strip())
                if line:
                    addresses.append(line)
            elif isinstance(adr, str) and adr.strip():
                addresses.append(adr.strip())
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    found = contacts_in_text(soup.get_text(" ", strip=True))
    unique, keys = [], set()
    for p in phones + found["phones"]:
        if phone_key(p) not in keys:
            keys.add(phone_key(p))
            unique.append(p)
    return {"phones": unique[:3],
            "emails": list(dict.fromkeys(e for e in emails + found["emails"]
                                         if not e.lower().endswith(_BAD_EMAIL_END)))[:3],
            "addresses": list(dict.fromkeys(addresses + found["addresses"]))[:3]}


def _ld_nodes(data: Any) -> Iterable[Any]:
    if isinstance(data, list):
        for d in data:
            yield from _ld_nodes(d)
    elif isinstance(data, dict):
        yield data
        for key in ("@graph", "location", "seller", "provider", "publisher"):
            if key in data:
                yield from _ld_nodes(data[key])


def location_tier(text: str | None, home_city: str = "Thunder Bay") -> tuple[str | None, str | None]:
    """(market tier, what it was based on) from an address or location text: local (home city or P7 postal
    code), regional (rest of Northern Ontario and Ontario), canada, us; None when nothing locates it."""
    t = text or ""
    if not t.strip():
        return None, None
    m = _POSTAL.search(t.upper())
    if m:  # the postal code decides; a town name alone can be a street ("Thunder Bay Rd") or a delivery area
        if m.group(1).startswith("P7"):
            return "local", f"address in {home_city} (P7 postal code)"
        if m.group(1)[0] in "PKLMN":
            return "regional", "Ontario postal code"
        return "canada", "Canadian postal code"
    if home_city.lower() in t.lower():
        return "local", f"address in {home_city}"
    if re.search(r"\b(ON|Ontario)\b", t):
        return "regional", "Ontario address"
    if re.search(r"\b(AB|BC|MB|NB|NL|NS|NT|NU|PE|QC|SK|YT|Alberta|British Columbia|Manitoba|Quebec|Québec|"
                 r"Saskatchewan|Nova Scotia|New Brunswick)\b", t):
        return "canada", "Canadian address"
    if _US_ZIP.search(t):
        return "us", "US address"
    return None, None


# ------------------------------------------------------- price kinds, badges
_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
# a finished sale: what an item sold for
_SOLD = re.compile(r"\bsold\s+(?:for|at)\b|\bsold\s+price\b|\bsold\s*:\s*(?:c\s*)?\$|\bsold\s+(?:on\s+)?" + _MONTHS +
                   r"\s+\d{1,2}|\bprice\s+realized\b|\bhammer\s+price\b|\b(?:auction|bidding|lot|sale)\s+"
                   r"(?:ended|closed)\b|\bended\s+(?:on\s+)?" + _MONTHS, re.I)
# an auction still running: its bid is not the final price
_LIVE_BID = re.compile(r"\b(?:current|high(?:est)?|leading|top)\s+bid\b|\bbid\s+now\b|\b(?:starting|opening|minimum)"
                       r"\s+bid\b|\bplace\s+(?:a\s+)?bid\b|\bbids?\s*:\s*\d|\bends\s+in\b|\b(?:closes|closing|ends)\s+"
                       r"(?:on\s+|in\s+|at\s+)?(?:\d|" + _MONTHS + r"|today|tomorrow)|\btime\s+left\b|\bso\s+far\b", re.I)
# ambiguous on their own ("winning bid $500"): a completed sale only when nothing says the auction is live
_FINAL_BID = re.compile(r"\b(?:winning|final)\s+bid\b", re.I)


_BADGES = re.compile(r"amazon'?s\s+choice|#?1\s+best\s+seller|\bbest\s+seller\b|top\s+rated(?:\s+(?:plus|seller))?|"
                     r"verified\s+supplier|gold\s+supplier|trade\s+assurance|overall\s+pick|top\s+brand|"
                     r"verified\s+seller|audited\s+(?:supplier|manufacturer)", re.I)


def price_kind(text: str, start: int = 0, end: int | None = None) -> str:
    """'completed_sale', 'current_bid' or 'asking' for a price at text[start:end] (looks 80 chars around it).
    A sale that says it's sold or ended wins; then any sign the auction is still running; then 'winning bid'."""
    end = len(text or "") if end is None else end
    window = (text or "")[max(0, start - 80): end + 80]
    if _SOLD.search(window):
        return "completed_sale"
    if _LIVE_BID.search(window):
        return "current_bid"
    if _FINAL_BID.search(window):
        return "completed_sale"
    return "asking"


def badges(text: str) -> list[str]:
    """Marketplace badges ('Amazon's Choice', 'Verified Supplier') - not proof of quality or seller identity."""
    return list(dict.fromkeys(m.group(0).strip() for m in _BADGES.finditer(text or "")))[:3]


def contact_link(html: str, base_url: str) -> str | None:
    """The page's own 'Contact us' link (same site only)."""
    soup = BeautifulSoup(html or "", "html.parser")
    base_host = (urlparse(base_url).hostname or "").lower().removeprefix("www.")
    for a in soup.find_all("a", href=True):
        label = f"{a.get_text(' ', strip=True)} {a['href']}".lower()
        if "contact" not in label:
            continue
        url = urljoin(base_url, a["href"].strip())
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        if url.startswith(("http://", "https://")) and host == base_host and url.rstrip("/") != base_url.rstrip("/"):
            return url.split("#")[0]
    return None
