"""SQLite persistence: searches, comparisons, price observations, FX rates.

SQLite keeps setup to zero (a single file under ./data). The repository
functions below are the only place SQL lives, so a later move to Postgres
only touches this module.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    normalized_query TEXT NOT NULL,
    input_type TEXT NOT NULL,
    depth TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    comparison_id INTEGER,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_searches_created ON searches(created_at);

CREATE TABLE IF NOT EXISTS comparisons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    query TEXT NOT NULL,
    normalized_query TEXT NOT NULL,
    product_key TEXT,
    saved INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    assumptions_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_researched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comparisons_norm ON comparisons(normalized_query);

CREATE TABLE IF NOT EXISTS price_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comparison_id INTEGER REFERENCES comparisons(id) ON DELETE SET NULL,
    search_id INTEGER,
    product_key TEXT,
    product_title TEXT NOT NULL,
    supplier TEXT,
    supplier_domain TEXT,
    supplier_country TEXT,
    price REAL,
    price_high REAL,
    currency TEXT,
    currency_basis TEXT,
    price_cad REAL,
    fx_rate REAL,
    fx_date TEXT,
    pack_qty REAL,
    unit_price REAL,
    price_basis TEXT NOT NULL,
    price_type TEXT NOT NULL,
    condition TEXT,
    match_level TEXT,
    url TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    specs_json TEXT,
    moq TEXT,
    shipping TEXT,
    warranty TEXT,
    availability TEXT,
    source_provider TEXT
);
CREATE INDEX IF NOT EXISTS idx_obs_product ON price_observations(product_key, observed_at);
CREATE INDEX IF NOT EXISTS idx_obs_comparison ON price_observations(comparison_id);

CREATE TABLE IF NOT EXISTS clarifications (
    key TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    answers_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fx_rates (
    currency TEXT NOT NULL,
    rate_date TEXT NOT NULL,
    rate_to_cad REAL NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (currency, rate_date)
);

CREATE TABLE IF NOT EXISTS supplier_profiles (
    supplier_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    preferred INTEGER NOT NULL DEFAULT 0,
    email TEXT,
    phone TEXT,
    notes TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_prices (
    supplier_key TEXT NOT NULL,
    product_key TEXT NOT NULL,
    unit_price_cad REAL NOT NULL,
    unit_label TEXT NOT NULL,
    valid_until TEXT,
    notes TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (supplier_key, product_key)
);

CREATE TABLE IF NOT EXISTS supplier_quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comparison_id INTEGER NOT NULL REFERENCES comparisons(id) ON DELETE CASCADE,
    supplier_key TEXT NOT NULL,
    supplier_name TEXT NOT NULL,
    method TEXT NOT NULL,
    status TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    quantity INTEGER,
    unit_price REAL,
    currency TEXT NOT NULL DEFAULT 'CAD',
    fx_rate_to_cad REAL,
    shipping_cad REAL,
    other_cad REAL NOT NULL DEFAULT 0,
    lead_days INTEGER,
    valid_until TEXT,
    specs_confirmed INTEGER NOT NULL DEFAULT 0,
    reference TEXT,
    notes TEXT,
    requested_at TEXT,
    received_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(comparison_id, supplier_key)
);
CREATE INDEX IF NOT EXISTS idx_supplier_quotes_comparison ON supplier_quotes(comparison_id);

CREATE TABLE IF NOT EXISTS quote_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    project_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comparison_watches (
    comparison_id INTEGER PRIMARY KEY REFERENCES comparisons(id) ON DELETE CASCADE,
    enabled INTEGER NOT NULL DEFAULT 0,
    interval_days INTEGER NOT NULL DEFAULT 7,
    max_runs_per_month INTEGER NOT NULL DEFAULT 4,
    next_due_at TEXT,
    run_month TEXT,
    runs_this_month INTEGER NOT NULL DEFAULT 0
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).replace(microsecond=0).isoformat()


class Database:
    """Thin thread-safe wrapper around one SQLite file."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if str(self.path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(searches)")}
        if "cost_usd" not in cols:  # added after the first release
            self._conn.execute("ALTER TABLE searches ADD COLUMN cost_usd REAL")
        if "hidden" not in cols:  # "Clear list" hides searches; the rows stay so this month's spend still counts
            self._conn.execute("ALTER TABLE searches ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
        self._conn.commit()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------------------------------------------- searches
    def create_search(self, query: str, normalized: str, input_type: str, depth: str) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO searches (query, normalized_query, input_type, depth, status, created_at)"
                " VALUES (?, ?, ?, ?, 'running', ?)",
                (query, normalized, input_type, depth, iso()),
            )
            return int(cur.lastrowid)

    def finish_search(self, search_id: int, status: str, comparison_id: int | None = None,
                      error: str | None = None, cost_usd: float | None = None) -> None:
        with self.tx() as c:
            c.execute(
                "UPDATE searches SET status = ?, comparison_id = ?, error = ?, finished_at = ?, cost_usd = ?"
                " WHERE id = ?",
                (status, comparison_id, error, iso(), cost_usd, search_id),
            )

    def month_spend(self, now: datetime | None = None) -> float:
        """Estimated Anthropic spend (US$) of searches started this calendar month (UTC)."""
        start = (now or utcnow()).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        with self.tx() as c:
            row = c.execute("SELECT COALESCE(SUM(cost_usd), 0) AS s FROM searches WHERE created_at >= ?",
                            (iso(start),)).fetchone()
        return float(row["s"])

    def record_spend(self, label: str, kind: str, cost_usd: float | None) -> None:
        """AI spend outside a research (reading a photo): counted in this month's spend, not shown as a search."""
        now = iso()
        with self.tx() as c:
            c.execute("INSERT INTO searches (query, normalized_query, input_type, depth, status, created_at,"
                      " finished_at, cost_usd, hidden) VALUES (?, ?, ?, ?, 'done', ?, ?, ?, 1)",
                      (label, label.lower(), kind, kind, now, now, cost_usd))

    def clear_recent_searches(self) -> int:
        """Hide every search from the recent list. Saved comparisons, price history and spend records stay."""
        with self.tx() as c:
            return c.execute("UPDATE searches SET hidden = 1 WHERE hidden = 0 AND status != 'running'").rowcount

    def recent_searches(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.tx() as c:
            rows = c.execute(
                "SELECT s.*, c.title AS comparison_title, c.saved AS comparison_saved"
                " FROM searches s LEFT JOIN comparisons c ON c.id = s.comparison_id"
                " WHERE s.hidden = 0 ORDER BY s.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------- quote projects
    def list_quote_projects(self) -> list[dict[str, Any]]:
        with self.tx() as c:
            rows = c.execute("SELECT id, title, updated_at FROM quote_projects ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]

    def get_quote_project(self, project_id: int) -> dict[str, Any] | None:
        with self.tx() as c:
            row = c.execute("SELECT * FROM quote_projects WHERE id = ?", (project_id,)).fetchone()
        return {**json.loads(row["project_json"]), "id": row["id"], "updated_at": row["updated_at"]} if row else None

    def save_quote_project(self, project: dict[str, Any], project_id: int | None = None) -> int:
        now = iso()
        data = json.dumps(project)
        with self.tx() as c:
            if project_id is not None:
                cur = c.execute("UPDATE quote_projects SET title = ?, project_json = ?, updated_at = ? WHERE id = ?",
                                (project["title"], data, now, project_id))
                if not cur.rowcount:
                    raise ValueError("Quote project not found")
                return project_id
            cur = c.execute("INSERT INTO quote_projects (title, project_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
                            (project["title"], data, now, now))
            return int(cur.lastrowid)

    # ------------------------------------------------------------- comparisons
    def save_comparison(self, *, title: str, query: str, normalized: str, product_key: str | None,
                        result: dict[str, Any], comparison_id: int | None = None,
                        assumptions: dict[str, Any] | None = None) -> int:
        now = iso()
        payload = json.dumps(result)
        with self.tx() as c:
            if comparison_id is not None:
                # A refresh keeps the user's name for the comparison
                c.execute(
                    "UPDATE comparisons SET product_key = ?, result_json = ?,"
                    " last_researched_at = ?, updated_at = ? WHERE id = ?",
                    (product_key, payload, result.get("researched_at", now), now, comparison_id),
                )
                return comparison_id
            cur = c.execute(
                "INSERT INTO comparisons (title, query, normalized_query, product_key, result_json,"
                " assumptions_json, created_at, last_researched_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (title, query, normalized, product_key, payload, json.dumps(assumptions or {}),
                 now, result.get("researched_at", now), now),
            )
            return int(cur.lastrowid)

    def get_comparison(self, comparison_id: int) -> dict[str, Any] | None:
        with self.tx() as c:
            row = c.execute("SELECT * FROM comparisons WHERE id = ?", (comparison_id,)).fetchone()
        if not row:
            return None
        out = dict(row)
        out["result"] = json.loads(out.pop("result_json"))
        out["assumptions"] = json.loads(out.pop("assumptions_json") or "{}")
        out["saved"] = bool(out["saved"])
        return out

    def update_comparison_meta(self, comparison_id: int, *, saved: bool | None = None,
                               title: str | None = None, notes: str | None = None,
                               assumptions: dict[str, Any] | None = None,
                               result: dict[str, Any] | None = None) -> None:
        sets, args = [], []
        if saved is not None:
            sets.append("saved = ?"); args.append(1 if saved else 0)
        if title is not None:
            sets.append("title = ?"); args.append(title)
        if notes is not None:
            sets.append("notes = ?"); args.append(notes)
        if assumptions is not None:
            sets.append("assumptions_json = ?"); args.append(json.dumps(assumptions))
        if result is not None:
            sets.append("result_json = ?"); args.append(json.dumps(result))
        if not sets:
            return
        sets.append("updated_at = ?"); args.append(iso())
        args.append(comparison_id)
        with self.tx() as c:
            c.execute(f"UPDATE comparisons SET {', '.join(sets)} WHERE id = ?", args)

    def results_for(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        """Stored results by comparison id (for showing each one's outcome in lists)."""
        ids = [int(i) for i in ids if i is not None][:100]
        if not ids:
            return {}
        with self.tx() as c:
            rows = c.execute(f"SELECT id, result_json FROM comparisons WHERE id IN ({','.join('?' * len(ids))})",
                             ids).fetchall()
        return {r["id"]: json.loads(r["result_json"]) for r in rows}

    def list_comparisons(self, saved_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
        sql = ("SELECT id, title, query, product_key, saved, notes, created_at, last_researched_at, updated_at"
               " FROM comparisons")
        if saved_only:
            sql += " WHERE saved = 1"
        sql += " ORDER BY last_researched_at DESC LIMIT ?"
        with self.tx() as c:
            rows = c.execute(sql, (limit,)).fetchall()
        return [dict(r) | {"saved": bool(r["saved"])} for r in rows]

    def delete_comparison(self, comparison_id: int) -> bool:
        with self.tx() as c:
            cur = c.execute("DELETE FROM comparisons WHERE id = ?", (comparison_id,))
            return cur.rowcount > 0

    def find_recent_comparison(self, normalized: str, within_hours: int,
                               request: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Reuse a result only when its research inputs match this request.

        Several comparisons can share the same words, so check every recent one
        instead of only the most recent result for that query.
        """
        cutoff = iso(utcnow() - timedelta(hours=within_hours))
        with self.tx() as c:
            rows = c.execute(
                "SELECT id, title, last_researched_at, result_json FROM comparisons"
                " WHERE normalized_query = ? AND last_researched_at >= ?"
                " ORDER BY last_researched_at DESC, id DESC",
                (normalized, cutoff),
            ).fetchall()
        for row in rows:
            result = json.loads(row["result_json"])
            if request is not None and any(
                (result.get("plan") or {}).get("used_ok") != value if key == "used_ok"
                else result.get(key) != value
                for key, value in request.items()
            ):
                continue
            return {key: row[key] for key in ("id", "title", "last_researched_at")}
        return None

    # ------------------------------------------------------------ observations
    def add_observations(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        cols = ["comparison_id", "search_id", "product_key", "product_title", "supplier",
                "supplier_domain", "supplier_country", "price", "price_high", "currency",
                "currency_basis", "price_cad", "fx_rate", "fx_date", "pack_qty", "unit_price",
                "price_basis", "price_type", "condition", "match_level", "url", "observed_at",
                "specs_json", "moq", "shipping", "warranty", "availability", "source_provider"]
        sql = f"INSERT INTO price_observations ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        with self.tx() as c:
            c.executemany(sql, [tuple(r.get(k) for k in cols) for r in rows])
        return len(rows)

    def observations(self, *, product_key: str | None = None, comparison_id: int | None = None,
                     limit: int = 1000) -> list[dict[str, Any]]:
        where, args = [], []
        if product_key:
            where.append("product_key = ?"); args.append(product_key)
        if comparison_id is not None:
            where.append("comparison_id = ?"); args.append(comparison_id)
        sql = "SELECT * FROM price_observations"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY observed_at DESC, id DESC LIMIT ?"  # newest first so the limit never hides recent data
        args.append(limit)
        with self.tx() as c:
            rows = c.execute(sql, args).fetchall()
        return [dict(r) for r in reversed(rows)]

    # --------------------------------------------------------- clarifications
    def get_answers(self, key: str) -> dict[str, Any]:
        with self.tx() as c:
            row = c.execute("SELECT answers_json FROM clarifications WHERE key = ?", (key,)).fetchone()
        return json.loads(row["answers_json"]) if row else {}

    def save_answers(self, key: str, query: str, answers: dict[str, Any]) -> None:
        merged = {**self.get_answers(key), **answers}
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO clarifications (key, query, answers_json, updated_at) VALUES (?, ?, ?, ?)",
                      (key, query, json.dumps(merged), iso()))

    # -------------------------------------------------------------------- fx
    def get_fx(self, currency: str, max_age_hours: int = 24) -> dict[str, Any] | None:
        cutoff = iso(utcnow() - timedelta(hours=max_age_hours))
        with self.tx() as c:
            row = c.execute(
                "SELECT * FROM fx_rates WHERE currency = ? AND fetched_at >= ?"
                " ORDER BY rate_date DESC LIMIT 1",
                (currency, cutoff),
            ).fetchone()
        return dict(row) if row else None

    def put_fx(self, currency: str, rate_date: str, rate_to_cad: float, source: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO fx_rates (currency, rate_date, rate_to_cad, source, fetched_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (currency, rate_date, rate_to_cad, source, iso()),
            )

    # ------------------------------------------------------ supplier workflow
    def supplier_profiles(self) -> dict[str, dict[str, Any]]:
        with self.tx() as c:
            rows = c.execute("SELECT * FROM supplier_profiles").fetchall()
        return {r["supplier_key"]: dict(r) | {"preferred": bool(r["preferred"])} for r in rows}

    def put_supplier_profile(self, row: dict[str, Any]) -> dict[str, Any]:
        keys = ("supplier_key", "name", "preferred", "email", "phone", "notes")
        values = [row.get(k) for k in keys]
        values[2] = int(bool(values[2]))
        with self.tx() as c:
            c.execute(
                "INSERT INTO supplier_profiles (" + ",".join(keys) + ",updated_at) VALUES (" +
                ",".join("?" for _ in keys) + ",?) ON CONFLICT(supplier_key) DO UPDATE SET " +
                ",".join(f"{k}=excluded.{k}" for k in keys[1:]) + ",updated_at=excluded.updated_at",
                (*values, iso()),
            )
            saved = c.execute("SELECT * FROM supplier_profiles WHERE supplier_key=?", (row["supplier_key"],)).fetchone()
        return dict(saved) | {"preferred": bool(saved["preferred"])}

    def account_prices_for(self, product_key: str | None) -> dict[str, dict[str, Any]]:
        if not product_key:
            return {}
        with self.tx() as c:
            rows = c.execute("SELECT * FROM account_prices WHERE product_key=?", (product_key,)).fetchall()
        return {r["supplier_key"]: dict(r) for r in rows}

    def put_account_price(self, row: dict[str, Any]) -> dict[str, Any]:
        keys = ("supplier_key", "product_key", "unit_price_cad", "unit_label", "valid_until", "notes")
        with self.tx() as c:
            c.execute("INSERT INTO account_prices (" + ",".join(keys) + ",updated_at) VALUES (?,?,?,?,?,?,?)"
                      " ON CONFLICT(supplier_key,product_key) DO UPDATE SET unit_price_cad=excluded.unit_price_cad,"
                      "unit_label=excluded.unit_label,valid_until=excluded.valid_until,notes=excluded.notes,"
                      "updated_at=excluded.updated_at", (*[row.get(k) for k in keys], iso()))
            saved = c.execute("SELECT * FROM account_prices WHERE supplier_key=? AND product_key=?",
                              (row["supplier_key"], row["product_key"])).fetchone()
        return dict(saved)

    def quotes_for(self, comparison_id: int) -> list[dict[str, Any]]:
        with self.tx() as c:
            rows = c.execute("SELECT * FROM supplier_quotes WHERE comparison_id=? ORDER BY updated_at DESC, id DESC",
                             (comparison_id,)).fetchall()
        return [dict(r) | {"specs_confirmed": bool(r["specs_confirmed"])} for r in rows]

    def put_quote(self, comparison_id: int, row: dict[str, Any]) -> dict[str, Any]:
        keys = ("supplier_key", "supplier_name", "method", "status", "email", "phone", "quantity",
                "unit_price", "currency", "fx_rate_to_cad", "shipping_cad", "other_cad", "lead_days",
                "valid_until", "specs_confirmed", "reference", "notes")
        vals = [row.get(k) for k in keys]
        vals[14] = int(bool(vals[14]))
        now = iso()
        with self.tx() as c:
            old = c.execute("SELECT requested_at,received_at FROM supplier_quotes WHERE comparison_id=? AND supplier_key=?",
                            (comparison_id, row["supplier_key"])).fetchone()
            requested = old["requested_at"] if old else None
            received = old["received_at"] if old else None
            if row["status"] in ("requested", "received") and not requested:
                requested = now
            if row["status"] == "received" and not received:
                received = now
            c.execute("INSERT INTO supplier_quotes (comparison_id," + ",".join(keys) +
                      ",requested_at,received_at,updated_at) VALUES (" +
                      ",".join("?" for _ in range(len(keys) + 4)) + ") ON CONFLICT(comparison_id,supplier_key)"
                      " DO UPDATE SET " + ",".join(f"{k}=excluded.{k}" for k in keys[1:]) +
                      ",requested_at=excluded.requested_at,received_at=excluded.received_at,"
                      "updated_at=excluded.updated_at",
                      (comparison_id, *vals, requested, received, now))
            saved = c.execute("SELECT * FROM supplier_quotes WHERE comparison_id=? AND supplier_key=?",
                              (comparison_id, row["supplier_key"])).fetchone()
        return dict(saved) | {"specs_confirmed": bool(saved["specs_confirmed"])}

    def watch_for(self, comparison_id: int) -> dict[str, Any] | None:
        with self.tx() as c:
            row = c.execute("SELECT * FROM comparison_watches WHERE comparison_id=?", (comparison_id,)).fetchone()
        return dict(row) | {"enabled": bool(row["enabled"])} if row else None

    def put_watch(self, comparison_id: int, enabled: bool, interval_days: int,
                  max_runs_per_month: int) -> dict[str, Any]:
        now = utcnow()
        due = iso(now + timedelta(days=interval_days)) if enabled else None
        with self.tx() as c:
            c.execute("INSERT INTO comparison_watches (comparison_id,enabled,interval_days,max_runs_per_month,next_due_at)"
                      " VALUES (?,?,?,?,?) ON CONFLICT(comparison_id) DO UPDATE SET enabled=excluded.enabled,"
                      "interval_days=excluded.interval_days,max_runs_per_month=excluded.max_runs_per_month,"
                      "next_due_at=excluded.next_due_at", (comparison_id, int(enabled), interval_days,
                                                        max_runs_per_month, due))
        return self.watch_for(comparison_id)

    def due_watches(self) -> list[dict[str, Any]]:
        with self.tx() as c:
            rows = c.execute("SELECT w.*,c.query,c.result_json FROM comparison_watches w JOIN comparisons c"
                             " ON c.id=w.comparison_id WHERE w.enabled=1 AND w.next_due_at<=?",
                             (iso(),)).fetchall()
        return [dict(r) | {"result": json.loads(r["result_json"])} for r in rows]

    def mark_watch_started(self, comparison_id: int) -> None:
        now = utcnow()
        month = now.strftime("%Y-%m")
        with self.tx() as c:
            row = c.execute("SELECT interval_days,run_month,runs_this_month FROM comparison_watches"
                            " WHERE comparison_id=?", (comparison_id,)).fetchone()
            if not row:
                return
            count = row["runs_this_month"] if row["run_month"] == month else 0
            c.execute("UPDATE comparison_watches SET run_month=?,runs_this_month=?,next_due_at=?"
                      " WHERE comparison_id=?", (month, count + 1,
                       iso(now + timedelta(days=row["interval_days"])), comparison_id))

    def backup_bytes(self) -> bytes:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "purchasing-backup.db"
            with sqlite3.connect(path) as dest, self._lock:
                self._conn.backup(dest)
            return path.read_bytes()

    def restore_bytes(self, data: bytes) -> Path:
        if not data.startswith(b"SQLite format 3\x00"):
            raise ValueError("This is not a SQLite backup.")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "restore.db"
            path.write_bytes(data)
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as source:
                if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("The backup is damaged.")
                names = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {"searches", "comparisons", "price_observations", "supplier_quotes",
                        "supplier_profiles", "account_prices", "comparison_watches"}.issubset(names):
                    raise ValueError("This backup is missing purchasing data tables.")
                backup_dir = self.path.parent / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                before = backup_dir / f"before-restore-{utcnow().strftime('%Y%m%d-%H%M%S')}.db"
                with self._lock:
                    with sqlite3.connect(before) as dest:
                        self._conn.backup(dest)
                    source.backup(self._conn)
        return before
