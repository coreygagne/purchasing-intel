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
    page.wait_for_selector(".three-quotes")
    assert "Three distinct supplier options" in page.inner_text(".three-quotes")
    names = page.locator(".three-quotes > .quote-grid > .quote-option h3").all_inner_texts()
    assert len(names) == len(set(names)) and len(names) >= 2
    assert "Shipping" in page.inner_text(".three-quotes")
    first = page.locator(".three-quotes > .quote-grid > .quote-option").first
    first.locator("summary:has-text('Save contact details')").click()
    contact = first.locator(".quote-form").nth(1)
    contact.locator('input[name="email"]').fill("sales@example.test")
    contact.locator('button[type="submit"]').click()
    page.wait_for_selector(".three-quotes a:has-text('Draft email')")
    first = page.locator(".three-quotes > .quote-grid > .quote-option").first
    first.locator("summary:has-text('Record email or phone quote')").click()
    form = first.locator(".quote-form").first
    form.locator('select[name="status"]').select_option("received")
    form.locator('input[name="unit_price"]').fill("100")
    form.locator('input[name="shipping_cad"]').fill("0")
    form.locator('input[name="specs_confirmed"]').check()
    form.locator('button[type="submit"]').click()
    page.wait_for_selector(".three-quotes > .quote-grid > .quote-option:has-text('Supplier response')")
    assert "KMS Tools" in page.inner_text(".lead")
    assert ("Price lead: delivery cost to confirm" in page.inner_text(".lead") or
            "Recommended: best-supported option" in page.inner_text(".lead"))
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
    page.wait_for_selector(".three-quotes")
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
    page.wait_for_selector(".three-quotes")
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


def test_verdict_shows_price_and_next_step(servers, browser):
    page = browser.new_page(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    page.goto(servers["ready"] + "/#/c/1")
    page.wait_for_selector(".lead .figure")
    assert "CAD" in page.inner_text(".lead .figure .amount")
    assert page.locator(".legend-box").get_attribute("open") is None  # the marks legend is folded away
    page.click("text=Coverage")
    page.click(".lead >> text=Suppliers & quote drafts")
    assert page.inner_text(".tabs [aria-selected=true]") == "Suppliers & quotes"
    page.close()


def _png(path, w=40, h=30):
    import struct
    import zlib
    rows = b"".join(b"\x00" + b"\x80\x40\x20" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    return path


def test_photo_without_ai_key_offers_google_lens(servers, browser, tmp_path):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(servers["ready"])
    page.set_input_files("#photo", str(_png(tmp_path / "nameplate.png")))
    page.wait_for_selector("text=Photo not read")
    assert "Anthropic key" in page.inner_text("#flash")
    assert page.get_attribute("#flash a:has-text('Try Google Lens')", "href").startswith("https://lens.google.com")
    assert errors == []
    page.close()


def test_clear_recent_searches(servers, browser):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(servers["ready"])
    page.wait_for_selector("button:has-text('Clear list')")
    page.once("dialog", lambda d: d.accept())
    page.click("button:has-text('Clear list')")
    page.wait_for_selector("text=Your searches will appear here.")
    assert "TX-4400 for maintenance shop" in page.inner_text(".home-lists")  # saved comparisons stay
    page.close()


def test_area_toggles_keep_one_on_and_are_sent(servers, browser):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(servers["ready"])
    page.click("text=Outside Thunder Bay")
    assert page.is_checked("#area-local") and not page.is_checked("#area-outside")
    page.click("text=In Thunder Bay")  # the last one on stays on
    assert page.is_checked("#area-local")
    page.fill("#q", "Acme TX-4400 torque widget")
    with page.expect_request(lambda r: r.url.endswith("/api/research")) as req:
        page.click("#search-btn")
        page.wait_for_selector("form.clarify, .progress, .notice, .lead")
        if page.locator("form.clarify").count():
            page.click("text=Skip questions")
    assert req.value.post_data_json["area"] == "local"
    page.click("text=Outside Thunder Bay")  # back to both for the other tests
    page.close()


def test_hovering_a_listing_link_shows_its_picture(servers, browser, tmp_path):
    import base64
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(servers["ready"] + "/#/c/1")
    page.wait_for_selector(".lead")
    pic = "data:image/png;base64," + base64.b64encode(_png(tmp_path / "p.png").read_bytes()).decode()
    page.evaluate("""(pic) => { const a = document.createElement('a'); a.href = 'https://dealer.example/1';
        a.id = 'test-link'; a.textContent = 'Test listing'; a.dataset.img = pic; document.querySelector('.lead').prepend(a); }""", pic)
    page.hover("#test-link")
    page.wait_for_selector(".peek:not([hidden])")
    assert "dealer.example" in page.inner_text(".peek .cap")
    page.mouse.move(5, 5)
    page.wait_for_selector(".peek", state="hidden")
    page.close()


def test_filters_panel_slider_and_apply_to_result(servers, browser):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(servers["ready"] + "/#/c/1")
    page.wait_for_selector(".lead")
    page.click("#filters-btn")
    assert page.is_visible("#filters") and page.is_visible("#filters-apply")
    page.fill("#price-max", "300")
    assert int(page.input_value("#price-hi")) < 1000  # the slider follows the box
    page.eval_on_selector("#price-lo", "(el) => { el.value = 100; el.dispatchEvent(new Event('input')); }")
    assert page.input_value("#price-min") != ""  # and the box follows the slider
    page.fill("#price-min", "")
    assert "Filters (1)" in page.inner_text("#filters-btn")
    with page.expect_response(lambda r: "/filters" in r.url and r.request.method == "PUT") as resp:
        page.click("#filters-apply")
    assert resp.value.ok
    page.wait_for_selector("text=Filters:")
    assert "up to CAD 300.00" in page.inner_text(".result-head")
    page.click("#filters-clear")
    page.click("#filters-apply")
    page.wait_for_selector("text=Filter these results")
    assert errors == []
    page.close()


def test_pasting_a_picture_starts_a_photo_search(servers, browser, tmp_path):
    import base64
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(servers["ready"])
    b64 = base64.b64encode(_png(tmp_path / "copied.png").read_bytes()).decode()
    page.evaluate("""(b64) => {
        const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        const dt = new DataTransfer();
        dt.items.add(new File([bytes], "copied.png", { type: "image/png" }));
        document.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true }));
    }""", b64)
    page.wait_for_selector("text=Photo not read")  # the test server has no AI key: Google Lens is offered instead
    page.close()


def test_filters_are_open_on_the_search_page_and_send_condition(servers, browser):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(servers["ready"])
    page.wait_for_selector("#filters", state="visible")  # part of the search, not hidden behind a button
    page.click("text=Used")
    page.fill("#price-max", "60000")
    page.fill("#year-min", "2015")
    page.fill("#hours-max", "5000")
    page.fill("#q", "used telehandler")
    with page.expect_request(lambda r: r.url.endswith("/api/research")) as req:
        page.click("#search-btn")
        page.wait_for_selector("form.clarify, .progress, .notice, .lead")
        if page.locator("form.clarify").count():
            page.click("text=Skip questions")
    sent = req.value.post_data_json["filters"]
    assert sent == {"price_max": 60000, "year_min": 2015, "hours_max": 5000, "condition": "used"}
    page.close()
