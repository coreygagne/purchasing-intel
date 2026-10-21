"""Serve the real app against the SIMULATED web, for UI testing only.

    python -m tests.serve_fake --port 8765 [--unconfigured]

All products, suppliers and prices come from tests/fakeweb.py (fictional
"Acme TX-4400" fixtures). The page shows a banner so screenshots can't be
mistaken for real research.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import uvicorn
from fastapi.responses import HTMLResponse

from app.config import Settings
from app.main import STATIC_DIR, create_app
from tests.fakeweb import SERP_SHOPPING, FakeWeb, with_local_supplier

BANNER = ('<div style="background:#a63a2a;color:#fff;padding:6px 16px;font:600 13px/1.4 sans-serif">'
          "TEST HARNESS: simulated web data (fictional products and prices). Not real research.</div>")


def build(unconfigured: bool = False):
    from app import fetch
    from tests.conftest import fake_resolve
    fetch.resolve_host = fake_resolve  # simulated hosts aren't in real DNS
    tmp = Path(tempfile.mkdtemp())
    settings = Settings(tavily_api_key=None if unconfigured else "tvly-test-key",
                        serpapi_api_key=None if unconfigured else "serp-test", database_path=tmp / "ui-test.db",
                        env_file=tmp / ".env")  # keys saved in the harness never touch the project's .env

    async def accept_any_key(key: str) -> None:  # the harness never contacts Anthropic
        return None

    app = create_app(settings, transport=with_local_supplier(FakeWeb(serp_body=SERP_SHOPPING)).transport(), key_checker=accept_any_key)
    # Replace "/" so the page carries the test banner
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/"]

    @app.get("/")
    def index() -> HTMLResponse:
        html = (STATIC_DIR / "index.html").read_text()
        return HTMLResponse(html.replace("<body>", "<body>" + BANNER, 1))

    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--unconfigured", action="store_true")
    args = ap.parse_args()
    uvicorn.run(build(args.unconfigured), host="127.0.0.1", port=args.port, log_level="warning")
