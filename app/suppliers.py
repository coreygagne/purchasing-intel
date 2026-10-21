"""Source / supplier classification.

The directory below is curated metadata about *what kind of site* a domain is
(e.g. "industrial distributor, Canada"). It intentionally makes no claims
about price levels or service quality - those must come from evidence.
Unknown domains are reported as unknown, never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# type keys
MANUFACTURER = "manufacturer"
DISTRIBUTOR = "industrial distributor"
RETAILER = "retailer"
MARKETPLACE = "marketplace"
B2B_MARKETPLACE = "B2B wholesale marketplace"
REVIEW = "professional review"
FORUM = "forum / user discussion"
VIDEO = "video"
COMPLAINTS = "supplier reviews / complaints"
GOVERNMENT = "government / regulator"
CLASSIFIEDS = "classifieds / used"
DEALS = "deal forum (past deals)"
SEARCH = "search results page"
AUCTION = "auction / surplus"
PROPERTY_SITE = "property listings"
BUSINESS_DIRECTORY = "business directory"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class SupplierInfo:
    name: str
    type: str
    country: str | None  # ISO-2 where the storefront sells from / to


DIRECTORY: dict[str, SupplierInfo] = {
    # Canadian industrial / trade distributors
    "grainger.ca": SupplierInfo("Grainger Canada", DISTRIBUTOR, "CA"),
    "acklandsgrainger.com": SupplierInfo("Grainger Canada (Acklands-Grainger)", DISTRIBUTOR, "CA"),
    "tenaquip.com": SupplierInfo("Tenaquip", DISTRIBUTOR, "CA"),
    "wajax.com": SupplierInfo("Wajax", DISTRIBUTOR, "CA"),
    "boltsupply.com": SupplierInfo("Bolt Supply House", DISTRIBUTOR, "CA"),
    "levitt-safety.com": SupplierInfo("Levitt Safety", DISTRIBUTOR, "CA"),
    "globalindustrial.ca": SupplierInfo("Global Industrial Canada", DISTRIBUTOR, "CA"),
    "uline.ca": SupplierInfo("Uline Canada", DISTRIBUTOR, "CA"),
    "napacanada.com": SupplierInfo("NAPA Canada", RETAILER, "CA"),
    "partsource.ca": SupplierInfo("PartSource", RETAILER, "CA"),
    "digikey.ca": SupplierInfo("DigiKey (Canada site)", DISTRIBUTOR, "CA"),
    # Canadian electrical distributors (wire, cable, Teck)
    "gerrie.com": SupplierInfo("Gerrie Electric", DISTRIBUTOR, "CA"),
    "nedco.ca": SupplierInfo("Nedco", DISTRIBUTOR, "CA"),
    "westburne.ca": SupplierInfo("Westburne", DISTRIBUTOR, "CA"),
    "guillevin.com": SupplierInfo("Guillevin", DISTRIBUTOR, "CA"),
    "eecol.com": SupplierInfo("EECOL Electric", DISTRIBUTOR, "CA"),
    "franklinempire.com": SupplierInfo("Franklin Empire", DISTRIBUTOR, "CA"),
    "texcan.com": SupplierInfo("Texcan", DISTRIBUTOR, "CA"),
    "lumen.ca": SupplierInfo("Lumen", DISTRIBUTOR, "CA"),
    "mouser.ca": SupplierInfo("Mouser (Canada site)", DISTRIBUTOR, "CA"),
    # Canadian retailers
    "princessauto.com": SupplierInfo("Princess Auto", RETAILER, "CA"),
    "kmstools.com": SupplierInfo("KMS Tools", RETAILER, "CA"),
    "canadiantire.ca": SupplierInfo("Canadian Tire", RETAILER, "CA"),
    "homedepot.ca": SupplierInfo("The Home Depot Canada", RETAILER, "CA"),
    "rona.ca": SupplierInfo("RONA", RETAILER, "CA"),
    "homehardware.ca": SupplierInfo("Home Hardware", RETAILER, "CA"),
    "leevalley.com": SupplierInfo("Lee Valley", RETAILER, "CA"),
    "staples.ca": SupplierInfo("Staples Canada", RETAILER, "CA"),
    "bestbuy.ca": SupplierInfo("Best Buy Canada", RETAILER, "CA"),
    "costco.ca": SupplierInfo("Costco Canada", RETAILER, "CA"),
    "marks.com": SupplierInfo("Mark's", RETAILER, "CA"),
    "toolup.ca": SupplierInfo("ToolUp (Canada)", RETAILER, "CA"),
    # Canadian marketplaces
    "amazon.ca": SupplierInfo("Amazon.ca", MARKETPLACE, "CA"),
    "walmart.ca": SupplierInfo("Walmart Canada", MARKETPLACE, "CA"),
    "ebay.ca": SupplierInfo("eBay Canada", MARKETPLACE, "CA"),
    "kijiji.ca": SupplierInfo("Kijiji", CLASSIFIEDS, "CA"),
    "autotrader.ca": SupplierInfo("AutoTrader.ca", CLASSIFIEDS, "CA"),
    "carpages.ca": SupplierInfo("CarPages.ca", CLASSIFIEDS, "CA"),
    # Auctions, liquidation and government surplus
    "rbauction.com": SupplierInfo("RB Global (Ritchie Bros.) auctions", AUCTION, None),
    "ironplanet.com": SupplierInfo("IronPlanet", AUCTION, None),
    "govdeals.ca": SupplierInfo("GovDeals Canada", AUCTION, "CA"),
    "gcsurplus.ca": SupplierInfo("GCSurplus (Government of Canada surplus sales)", AUCTION, "CA"),
    "govdeals.com": SupplierInfo("GovDeals", AUCTION, "US"),
    "machinerytrader.com": SupplierInfo("Machinery Trader", CLASSIFIEDS, None),
    "equipmenttrader.com": SupplierInfo("Equipment Trader", CLASSIFIEDS, "US"),
    # Property listings
    "realtor.ca": SupplierInfo("REALTOR.ca", PROPERTY_SITE, "CA"),
    "spacelist.ca": SupplierInfo("Spacelist", PROPERTY_SITE, "CA"),
    "loopnet.com": SupplierInfo("LoopNet", PROPERTY_SITE, None),
    "remax.ca": SupplierInfo("RE/MAX Canada", PROPERTY_SITE, "CA"),
    "royallepage.ca": SupplierInfo("Royal LePage", PROPERTY_SITE, "CA"),
    # Business directories (they list businesses and contacts; they don't sell)
    "yellowpages.ca": SupplierInfo("Yellow Pages Canada", BUSINESS_DIRECTORY, "CA"),
    "canada411.ca": SupplierInfo("Canada411", BUSINESS_DIRECTORY, "CA"),
    # US distributors / retailers / marketplaces
    "grainger.com": SupplierInfo("Grainger (US)", DISTRIBUTOR, "US"),
    "mscdirect.com": SupplierInfo("MSC Industrial Supply", DISTRIBUTOR, "US"),
    "fastenal.com": SupplierInfo("Fastenal", DISTRIBUTOR, "US"),
    "mcmaster.com": SupplierInfo("McMaster-Carr", DISTRIBUTOR, "US"),
    "globalindustrial.com": SupplierInfo("Global Industrial (US)", DISTRIBUTOR, "US"),
    "uline.com": SupplierInfo("Uline (US)", DISTRIBUTOR, "US"),
    "zoro.com": SupplierInfo("Zoro", DISTRIBUTOR, "US"),
    "digikey.com": SupplierInfo("DigiKey", DISTRIBUTOR, "US"),
    "mouser.com": SupplierInfo("Mouser", DISTRIBUTOR, "US"),
    "northerntool.com": SupplierInfo("Northern Tool", RETAILER, "US"),
    "homedepot.com": SupplierInfo("The Home Depot (US)", RETAILER, "US"),
    "lowes.com": SupplierInfo("Lowe's (US)", RETAILER, "US"),
    "acmetools.com": SupplierInfo("Acme Tools", RETAILER, "US"),
    "toolup.com": SupplierInfo("ToolUp (US)", RETAILER, "US"),
    "harborfreight.com": SupplierInfo("Harbor Freight", RETAILER, "US"),
    "amazon.com": SupplierInfo("Amazon.com", MARKETPLACE, "US"),
    "walmart.com": SupplierInfo("Walmart (US)", MARKETPLACE, "US"),
    "ebay.com": SupplierInfo("eBay", MARKETPLACE, "US"),
    # International marketplaces
    "alibaba.com": SupplierInfo("Alibaba.com", B2B_MARKETPLACE, "CN"),
    "made-in-china.com": SupplierInfo("Made-in-China.com", B2B_MARKETPLACE, "CN"),
    "globalsources.com": SupplierInfo("Global Sources", B2B_MARKETPLACE, None),
    "dhgate.com": SupplierInfo("DHgate", MARKETPLACE, "CN"),
    "aliexpress.com": SupplierInfo("AliExpress", MARKETPLACE, "CN"),
    "temu.com": SupplierInfo("Temu", MARKETPLACE, "CN"),
    "amazon.co.uk": SupplierInfo("Amazon UK", MARKETPLACE, "GB"),
    "amazon.de": SupplierInfo("Amazon Germany", MARKETPLACE, "DE"),
    # Reviews, discussion, complaints
    "reddit.com": SupplierInfo("Reddit", FORUM, None),
    "garagejournal.com": SupplierInfo("Garage Journal forum", FORUM, None),
    "quora.com": SupplierInfo("Quora", FORUM, None),
    "youtube.com": SupplierInfo("YouTube", VIDEO, None),
    "youtu.be": SupplierInfo("YouTube", VIDEO, None),
    "consumerreports.org": SupplierInfo("Consumer Reports", REVIEW, "US"),
    "rtings.com": SupplierInfo("RTINGS", REVIEW, None),
    "protoolreviews.com": SupplierInfo("Pro Tool Reviews", REVIEW, "US"),
    "toolguyd.com": SupplierInfo("ToolGuyd", REVIEW, "US"),
    "nytimes.com": SupplierInfo("New York Times / Wirecutter", REVIEW, "US"),
    "popularmechanics.com": SupplierInfo("Popular Mechanics", REVIEW, "US"),
    "bobvila.com": SupplierInfo("Bob Vila", REVIEW, "US"),
    "thespruce.com": SupplierInfo("The Spruce", REVIEW, "US"),
    "bing.com": SupplierInfo("Bing (search results)", SEARCH, None),
    "duckduckgo.com": SupplierInfo("DuckDuckGo (search results)", SEARCH, None),
    "search.yahoo.com": SupplierInfo("Yahoo (search results)", SEARCH, None),
    "slickdeals.net": SupplierInfo("Slickdeals", DEALS, "US"),
    "redflagdeals.com": SupplierInfo("RedFlagDeals", DEALS, "CA"),
    "camelcamelcamel.com": SupplierInfo("camelcamelcamel (Amazon price history)", DEALS, None),
    "ifixit.com": SupplierInfo("iFixit (repair guides)", FORUM, None),
    "trustpilot.com": SupplierInfo("Trustpilot", COMPLAINTS, None),
    "bbb.org": SupplierInfo("Better Business Bureau", COMPLAINTS, None),
    "sitejabber.com": SupplierInfo("Sitejabber", COMPLAINTS, None),
    # Government / regulators
    "recalls-rappels.canada.ca": SupplierInfo("Government of Canada Recalls", GOVERNMENT, "CA"),
    "canada.ca": SupplierInfo("Government of Canada", GOVERNMENT, "CA"),
    "cbsa-asfc.gc.ca": SupplierInfo("Canada Border Services Agency", GOVERNMENT, "CA"),
    "cpsc.gov": SupplierInfo("US Consumer Product Safety Commission", GOVERNMENT, "US"),
    "osha.gov": SupplierInfo("US OSHA", GOVERNMENT, "US"),
}

_TLD_COUNTRY = {
    ".ca": "CA", ".us": "US", ".co.uk": "GB", ".uk": "GB", ".cn": "CN", ".de": "DE", ".fr": "FR",
    ".it": "IT", ".es": "ES", ".nl": "NL", ".com.au": "AU", ".au": "AU", ".com.mx": "MX", ".mx": "MX",
    ".jp": "JP", ".in": "IN", ".kr": "KR", ".tw": "TW", ".hk": "HK", ".se": "SE", ".ch": "CH",
    ".com.br": "BR", ".br": "BR", ".pl": "PL", ".be": "BE", ".at": "AT", ".dk": "DK", ".fi": "FI", ".no": "NO",
    ".ie": "IE", ".nz": "NZ", ".sg": "SG", ".com.cn": "CN", ".vn": "VN", ".th": "TH", ".my": "MY", ".tr": "TR",
}

COUNTRY_NAMES = {
    "CA": "Canada", "US": "United States", "CN": "China", "GB": "United Kingdom", "DE": "Germany",
    "MX": "Mexico", "JP": "Japan", "AU": "Australia", "FR": "France", "IT": "Italy", "IN": "India",
    "KR": "South Korea", "TW": "Taiwan", "HK": "Hong Kong", "NL": "Netherlands", "ES": "Spain",
    "SE": "Sweden", "CH": "Switzerland", "BR": "Brazil", "PL": "Poland", "IE": "Ireland", "NZ": "New Zealand",
    "SG": "Singapore", "VN": "Vietnam", "TR": "Turkey",
}

COUNTRY_CURRENCY = {
    "CA": "CAD", "US": "USD", "CN": "CNY", "GB": "GBP", "DE": "EUR", "FR": "EUR", "IT": "EUR",
    "ES": "EUR", "NL": "EUR", "MX": "MXN", "JP": "JPY", "AU": "AUD", "IN": "INR", "KR": "KRW",
    "HK": "HKD", "SE": "SEK", "CH": "CHF", "TW": "TWD",
}

REVIEW_TYPES = {REVIEW, FORUM, VIDEO, COMPLAINTS, DEALS}
SELLER_TYPES = {MANUFACTURER, DISTRIBUTOR, RETAILER, MARKETPLACE, B2B_MARKETPLACE, CLASSIFIEDS, AUCTION, PROPERTY_SITE,
                UNKNOWN}


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _lookup(domain: str) -> SupplierInfo | None:
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        cand = ".".join(parts[i:])
        if cand in DIRECTORY:
            return DIRECTORY[cand]
    return None


def lookup_by_name(name: str) -> SupplierInfo | None:
    """Directory entry for a seller name such as Google Shopping's 'source' ("Home Depot Canada")."""
    n = re.sub(r"[^a-z0-9]", "", name.lower())
    if not n:
        return None
    partial: list[SupplierInfo] = []
    for dom, info in DIRECTORY.items():
        full = re.sub(r"[^a-z0-9]", "", info.name.lower())
        if full == n or re.sub(r"[^a-z0-9]", "", dom) == n:
            return info
        if len(n) >= 6 and (n in full or full in n) and info not in partial:
            partial.append(info)
    # Only accept a partial name match when it is unambiguous
    return partial[0] if len(partial) == 1 else None


def country_from_domain(domain: str) -> str | None:
    info = _lookup(domain)
    if info and info.country:
        return info.country
    for tld, cc in sorted(_TLD_COUNTRY.items(), key=lambda kv: -len(kv[0])):
        if domain.endswith(tld):
            return cc
    return None


@dataclass
class SourceClass:
    name: str
    type: str
    country: str | None
    country_basis: str  # "directory" | "domain suffix" | "unknown"
    in_directory: bool


def classify_source(url: str, title: str = "", brand_words: list[str] | None = None) -> SourceClass:
    domain = domain_of(url)
    info = _lookup(domain)
    if info:
        return SourceClass(info.name, info.type, info.country, "directory" if info.country else "unknown", True)
    cc = country_from_domain(domain)
    basis = "domain suffix" if cc else "unknown"
    root = domain.split(".")[-2] if domain.count(".") >= 1 else domain
    # Manufacturer site: the brand name from the request appears in the domain
    for word in brand_words or []:
        w = re.sub(r"[^a-z0-9]", "", word.lower())
        if len(w) >= 3 and w in re.sub(r"[^a-z0-9]", "", root):
            return SourceClass(domain, MANUFACTURER, cc, basis, False)
    lowered = f"{domain} {title}".lower()
    if re.search(r"\breview(s|ed)?\b|\bvs\.?\b|\bbest\b.*\b(20\d\d|tested)\b|\btested\b", lowered):
        return SourceClass(domain, REVIEW, cc, basis, False)
    if re.search(r"forum|community|discussion|thread", lowered):
        return SourceClass(domain, FORUM, cc, basis, False)
    return SourceClass(domain, UNKNOWN, cc, basis, False)
