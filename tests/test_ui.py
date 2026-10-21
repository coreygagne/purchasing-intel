"""Browser test of the main workflow (simulated web; skipped if Playwright/Chromium is unavailable)."""

import os
import socket
import threading
import time

import pytest
import uvicorn

pw = pytest.importorskip("playwright.sync_api")

from tests.serve_fake import build  # noqa: E402

CHROME = os.environ.get("PW_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def servers():
    out = {}
    threads = []
    for name, unconfigured in (("ready", False), ("unconfigured", True), ("setup", True)):
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(build(unconfigured), host="127.0.0.1", port=port, log_level="warning"))
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        threads.append((server, t))
        out[name] = f"http://127.0.0.1:{port}"
    for url in out.values():
        for _ in range(100):
            try:
                socket.create_connection((url.split(":")[1][2:], int(url.rsplit(":", 1)[1])), 0.2).close()
                break
            except OSError:
                time.sleep(0.05)
    yield out
    for server, t in threads:
        server.should_exit = True
        t.join(5)


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        kw = {"executable_path": CHROME} if os.path.exists(CHROME) else {}
        try:
            b = p.chromium.launch(**kw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium not available: {exc}")
        yield b
        b.close()


def test_unconfigured_shows_setup_and_disables_search(servers, browser):
    page = browser.new_page()
    page.goto(servers["unconfigured"])
    page.wait_for_selector("text=Connect a search provider to start")
    assert page.is_disabled("#search-btn")
    assert "Setup needed" in page.inner_text("#status-pill")
    page.close()


def test_research_save_reopen_and_tabs(servers, browser):
    errors = []
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(servers["ready"])
    page.fill("#q", "Acme TX-4400 torque widget")
    page.click("#search-btn")
    # clarify first: optional questions; answer one, leave the rest blank (skipped)
    page.wait_for_selector("text=A few questions first")
    page.fill('input[name="cq-quantity"]', "2")
    page.click("form.clarify button[type=submit]")
    page.wait_for_url("**/#/c/*", timeout=20000)
    page.wait_for_selector(".rec")
    recs = page.inner_text(".recs")
    assert "Lowest comparable price" in recs and "Best overall value" in recs
    assert "Canadian Tire" in recs and "KMS Tools" in recs
    assert "Recommended: best-supported option" in page.inner_text(".lead") and "KMS Tools" in page.inner_text(".lead")
    assert "Options side by side" in page.inner_text("#view") and "Market value" in page.inner_text("#view")
    assert "Assumed" in page.inner_text(".panel.assumed")
    assert page.locator("table.cmp").first.locator("tr.offer").count() == 3
    # suppliers tab (default): the local supplier first, with sourced contacts and a quote draft
    first = page.locator(".vendor").first
    assert "Northern Tool Supply Ltd" in first.inner_text() and "Thunder Bay" in first.inner_text()
    assert "(807) 555-0142" in first.inner_text() and "Google Maps listing" in first.inner_text()
    assert first.locator("a.btn:has-text('Open in email')").get_attribute("href").startswith("mailto:sales@")
    page.click("text=Coverage")
    page.wait_for_selector("text=Channels searched")
    assert "not every supplier" in page.inner_text(".tabpanel")
    # details on demand
    page.locator("table.cmp tr.offer .toggle").first.click()
    assert page.locator("text=Where the price came from").first.is_visible()
    # tabs
    page.click("text=Import & landed cost")
    page.fill('input[name="surtax_pct"]', "25")
    page.click("text=Recalculate")
    page.wait_for_selector("text=Your assumption")
    assert "Import checklist" in page.inner_text(".tabpanel")
    page.click("text=Price history")
    page.wait_for_selector("text=Not enough comparable history")
    page.click("text=Sources & method")
    page.wait_for_selector("text=Searches run")
    # save, then find it on the home page and reopen
    page.once("dialog", lambda d: d.accept("TX-4400 for maintenance shop"))
    page.click("button:has-text('Save')")
    page.wait_for_selector("text=Saved (remove)")
    page.click("text=New search")
    page.wait_for_selector("text=TX-4400 for maintenance shop")
    page.click("text=TX-4400 for maintenance shop")
    page.wait_for_selector(".rec")
    assert "Last researched" in page.inner_text(".result-head")
    # export links respond with files
    resp = page.request.get(servers["ready"] + page.get_attribute("text=Export Excel", "href"))
    assert resp.ok and resp.headers["content-type"].startswith("application/vnd.openxmlformats")
    # duplicate guard
    page.fill("#q", "acme tx-4400 torque widget")
    page.click("#search-btn")
    page.wait_for_selector("text=Already researched recently")
    assert errors == []
    page.close()


def test_phone_width_has_no_horizontal_scroll(servers, browser):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.goto(servers["ready"] + "/#/c/1")
    page.wait_for_selector(".rec")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    page.close()


def test_pasting_a_key_on_the_setup_screen_makes_the_app_ready(servers, browser):
    page = browser.new_page()
    page.goto(servers["setup"])
    page.wait_for_selector("#key-anthropic")
    assert page.is_disabled("#search-btn")
    page.fill("#key-anthropic", "sk-ant-wrongformat")
    page.click(".keyform button[type=submit]")
    page.wait_for_selector(".keyform .msg.err")
    assert "sk-ant-" in page.inner_text(".keyform .msg")
    page.fill("#key-anthropic", "sk-ant-api03-" + "B" * 40)
    page.click(".keyform button[type=submit]")
    page.wait_for_function("!document.querySelector('#search-btn').disabled")
    assert "Anthropic web search" in page.inner_text("#status-pill")
    assert "Anthropic spend this month: about US$0.00 of your US$10.00 monthly limit" in page.inner_text("#cost-hint")
    assert page.is_checked("input[name=depth][value=quick]")  # the low-cost depth is preselected
    page.close()
