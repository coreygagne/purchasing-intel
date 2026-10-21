"""CSV and Excel exports of a comparison. Values are exported exactly as stored."""

from __future__ import annotations

import csv
import io
from typing import Any

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def safe_cell(value: Any) -> Any:
    """Text from the web must never become a spreadsheet formula, or break the file."""
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        return value
    text = ILLEGAL_CHARACTERS_RE.sub("", str(value))
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        text = "'" + text
    return text

OFFER_COLUMNS: list[tuple[str, Any]] = [
    ("Offer", "id"),
    ("Supplier", "supplier"),
    ("Supplier type", "supplier_type"),
    ("Seller country", "country"),
    ("Product (as listed)", "product_title"),
    ("Model match", "match_level"),
    ("Condition", lambda o: o.get("condition") or "not stated"),
    ("Advertised price", "price"),
    ("Price high (range)", "price_high"),
    ("Currency", "currency"),
    ("Currency basis", "currency_basis"),
    ("Price evidence", "price_label"),
    ("Price type", "price_type"),
    ("Evidence text", "evidence_quote"),
    ("Pack qty", "pack_qty"),
    ("Unit price (calculated)", "unit_price"),
    ("Price CAD (calculated)", "price_cad"),
    ("FX rate to CAD", "fx_rate"),
    ("FX date", "fx_date"),
    ("Unit price CAD (calculated)", "unit_price_cad"),
    ("Priced per (length)", lambda o: ((f"{o['per_length_qty']:g} " if (o.get("per_length_qty") or 1) != 1 else "")
                                       + o["per_length"]) if o.get("per_length") else None),
    ("CAD per foot (calculated)", "per_ft_cad"),
    ("CAD for requested length (calculated)", "order_total_cad"),
    ("Requested specs stated", lambda o: ", ".join(o.get("spec_confirmed") or [])),
    ("Requested specs not stated", lambda o: ", ".join(o.get("spec_missing") or [])),
    ("Spec differences", lambda o: "; ".join(o.get("spec_conflicts") or [])),
    ("Delivered/landed CAD", lambda o: (o.get("delivered") or {}).get("value")),
    ("Delivered basis", lambda o: (o.get("delivered") or {}).get("label")),
    ("Delivered: missing", lambda o: ", ".join((o.get("delivered") or {}).get("missing") or [])),
    ("Shipping", "shipping_text"),
    ("Warranty", "warranty"),
    ("MOQ", "moq"),
    ("Bulk pricing mention", "bulk"),
    ("Availability", "availability"),
    ("Rating", lambda o: f"{o['rating']['value']}/{o['rating'].get('best') or 5} ({o['rating'].get('count') or '?'} ratings)" if o.get("rating") else None),
    ("Comparable", lambda o: "yes" if o.get("comparable") else "no"),
    ("Excluded because", lambda o: "; ".join(o.get("exclusion_reasons") or [])),
    ("Flags", lambda o: "; ".join(o.get("flags") or [])),
    ("URL", "url"),
    ("Observed at (UTC)", "observed_at"),
    ("Source", "source_id"),
]


def _col(name: str) -> int:
    """1-based position of an Offers column (for widths)."""
    return [c for c, _ in OFFER_COLUMNS].index(name) + 1


def _val(o: dict[str, Any], key: Any) -> Any:
    return key(o) if callable(key) else o.get(key)


def offers_csv(result: dict[str, Any]) -> str:
    """Offers as CSV (prices are observations, not quotes; see the 'Observed at' column)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c for c, _ in OFFER_COLUMNS])
    for o in result["offers"]:
        w.writerow([safe_cell(_val(o, k)) for _, k in OFFER_COLUMNS])
    return buf.getvalue()


def _sheet(wb: Workbook, title: str, header: list[str], rows: list[list[Any]], widths: dict[int, int] | None = None):
    ws = wb.create_sheet(title)
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3A5F")
        cell.alignment = Alignment(vertical="top", wrap_text=True)
    for r in rows:
        ws.append([safe_cell(v) for v in r])
    for i in range(1, len(header) + 1):
        ws.column_dimensions[get_column_letter(i)].width = (widths or {}).get(i, 18)
    ws.freeze_panes = "A2"
    return ws


def comparison_xlsx(comparison: dict[str, Any], history: list[dict[str, Any]]) -> bytes:
    result = comparison["result"]
    rec = result.get("recommendations") or {}
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    lines: list[list[Any]] = [
        ["Request", result["query"]],
        ["Identified as", result["identity"]["name"]],
        ["Model numbers", ", ".join(result["identity"].get("model_tokens") or []) or "none in request"],
        ["Last researched (UTC)", result["researched_at"]],
        ["Search providers", ", ".join(v for v in [result["providers"].get("web"), result["providers"].get("shopping")] if v)],
        ["AI analysis", result["providers"].get("llm") or "off"],
        ["Comparison basis", rec.get("basis") or "n/a"],
        [],
    ]
    for key, label in (("lowest", "LOWEST COMPARABLE PRICE"), ("best_value", "BEST OVERALL VALUE")):
        r = rec.get(key)
        if r:
            lines.append([label, f"{r['supplier']} - {r['currency']} {r['price']:,.2f}" + (
                f" (CAD {r['price_cad']:,.2f})" if r.get("price_cad") and r["currency"] != "CAD" else "")])
            lines.append(["Link", r["url"]])
            for e in r["explanation"]:
                lines.append(["", e])
            for f in r.get("factors", []):
                lines.append(["", f"{f['factor']}: {f['points']} pts - {f['evidence']}"])
        else:
            lines.append([label, "Not available - see notes"])
        lines.append([])
    for n in rec.get("notes", []):
        lines.append(["Note", n])
    for g in result.get("gaps", []):
        lines.append(["Gap / missing info", g])
    for c in result.get("conflicts", []):
        lines.append(["Conflict", c["text"]])
    for t in result.get("opportunities", []):
        lines.append(["Opportunity", t])
    for l in result.get("limits", []):
        lines.append(["Limit", l])
    lines.append(["Disclaimer", "Prices are observations from public sources at the time shown, not quotes. "
                                "'Calculated' values are arithmetic on observed prices; 'estimated' values use the "
                                "stated assumptions."])
    for row in lines:
        ws.append([safe_cell(v) for v in row])
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 120
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        if row and row[0].value and str(row[0].value).isupper():
            row[0].font = Font(bold=True)

    _sheet(wb, "Offers", [c for c, _ in OFFER_COLUMNS],
           [[_val(o, k) for _, k in OFFER_COLUMNS] for o in result["offers"]],
           {_col(name): w for name, w in (("Supplier", 28), ("Product (as listed)", 50), ("Evidence text", 50),
                                          ("Flags", 60))})
    _sheet(wb, "Sources", ["ID", "Title", "Type", "Name", "Country", "Domain", "URL", "Found by", "Retrieved (UTC)",
                           "Page read", "Page read note"],
           [[s["id"], s["title"], s["type"], s["name"], s["country"], s["domain"], s["url"],
             ", ".join(s.get("purposes") or []), s["retrieved_at"],
             ("yes" if s["fetch"]["ok"] else "no") if s.get("fetch") else "not attempted",
             (s.get("fetch") or {}).get("error")] for s in result["sources"]], {2: 50, 7: 60})
    q = result.get("quality") or {}
    qrows: list[list[Any]] = []
    for r in q.get("ratings", []):
        qrows.append(["Customer rating", f"{r['value']}/{r['best']} ({r.get('count') or '?'} ratings)", r["supplier"],
                      r["basis"], "yes" if r.get("exact_model") else "no", r["url"]])
    for kind, key in (("Reported issue (verbatim)", "issue_mentions"), ("Praise (verbatim)", "praise_mentions"),
                      ("Recall mention (verbatim)", "recall_mentions")):
        for m in q.get(key, []):
            qrows.append([kind, m["quote"], m["domain"], m["type"], "yes" if m.get("exact_model") else "no", m["url"]])
    summ = q.get("summary") or {}
    for kind in ("praise", "criticism", "reliability_issues"):
        for p in summ.get(kind, []) or []:
            qrows.append([f"AI summary - {kind.replace('_', ' ')}", p.get("point"),
                          ", ".join(p.get("source_ids") or []), "AI summary of cited sources (quotes verified)", "",
                          " | ".join(p.get("urls") or [])])
    _sheet(wb, "Quality evidence", ["Kind", "Text", "Source", "Source type", "Exact model", "URL"], qrows,
           {2: 80, 6: 60})
    _sheet(wb, "Price history", ["Observed at (UTC)", "Supplier", "Product", "Price", "Currency", "Price CAD",
                                 "Price basis", "Match", "Condition", "URL"],
           [[h["observed_at"], h["supplier"], h["product_title"], h["price"], h["currency"], h["price_cad"],
             h["price_basis"], h["match_level"], h["condition"], h["url"]] for h in history], {3: 50, 10: 60})
    a = comparison.get("assumptions") or result.get("assumptions") or {}
    arows = [[k, v if v is not None else "not set"] for k, v in a.items()]
    arows += [[n["topic"], n["text"]] for n in result.get("import_notes", [])]
    arows += [[f"FX {cur}", f"1 {cur} = {r['rate_to_cad']} CAD ({r['source']}, {r['rate_date']})"]
              for cur, r in (result.get("fx") or {}).items()]
    _sheet(wb, "Import & assumptions", ["Item", "Value / note"], arows, {1: 40, 2: 120})
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
