"""브라우저 스트리밍 SHA-256(static/js/sha256.js) 이 hashlib 과 같은 결과를 내는지 (Playwright 있을 때만)"""

import base64
import hashlib
import os
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
JS = (Path(__file__).resolve().parents[3] / "static" / "js" / "sha256.js").read_text()


@pytest.fixture(scope="module")
def page():
    try:
        p = sync_api.sync_playwright().start()
        browser = p.chromium.launch()
    except Exception:
        pytest.skip("Chromium 이 설치되어 있지 않음")
    pg = browser.new_page()
    pg.set_content("<html></html>")
    pg.add_script_tag(content=JS)
    yield pg
    browser.close()
    p.stop()


@pytest.mark.parametrize("size", [0, 1, 55, 56, 63, 64, 65, 1000, 4 * 1024 * 1024 + 3])
def test_streaming_sha256_matches_hashlib(page, size):
    data = os.urandom(size)
    got = page.evaluate(
        """b64 => { const bin = Uint8Array.from(atob(b64), c => c.charCodeAt(0)); const h = new Sha256();
        for (let o = 0; o < bin.length; o += 1000003) h.update(bin.subarray(o, o + 1000003)); return h.hex(); }""",
        base64.b64encode(data).decode(),
    )
    assert got == hashlib.sha256(data).hexdigest()
