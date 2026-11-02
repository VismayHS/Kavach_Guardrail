"""The console in a real (headless) browser: every screen renders cleanly, and the CFO-tier approval works.
Skipped without Playwright and its Chromium (pip install playwright && python -m playwright install chromium)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("playwright.sync_api")


def _browser_installed() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(os.environ.get("KAVACH_SKIP_UI") == "1" or not _browser_installed(),
                    reason="no headless Chromium (python -m playwright install chromium)")
def test_console_screens_and_quorum_approval():
    from tests.ui.console_check import main
    assert main() == 0
