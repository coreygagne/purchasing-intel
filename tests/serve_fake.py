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
from tests.fakeweb import SERP_SHOPPING, FakeWeb

BANNER = ('<div style="background:#a63a2a;color:#fff;padding:6px 16px;font:600 13px/1.4 sans-serif">'
          "TEST HARNESS: simulated web data (fictional products and prices). Not real research.</div>")


def build(unconfigured: bool = False):
    db = Path(tempfile.mkdtemp()) / "ui-test.db"
    settings = Settings(tavily_api_key=None if unconfigured else "tvly-test-key",
                        serpapi_api_key=None if unconfigured else "serp-test", database_path=db)
    app = create_app(settings, transport=FakeWeb(serp_body=SERP_SHOPPING).transport())
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
