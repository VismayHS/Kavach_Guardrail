"""Drive the KAVACH console in headless Chromium against a live server (python tests/ui/console_check.py).

Checks every route renders without page errors or console errors, then the CFO-tier approval flow end to end:
run the EUR 650,000 scenario, approve as CFO, change the approver, approve as Finance Director.
Exit code 0 = all good. Used by tests/test_console_ui.py when Playwright is installed.
"""
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def serve():
    import uvicorn

    from kavach import server
    server.AUTH_SECRET = None
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(200):
        if srv.started:
            break
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", srv


def main(routes=None) -> int:
    from playwright.sync_api import sync_playwright
    base, srv = serve()
    problems = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
        page.on("console", lambda m: problems.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
        for r in routes or ["agent", "scenarios", "check", "approvals", "windows", "receipts", "results", "rules"]:
            page.goto(f"{base}/#/{r}")
            page.wait_for_selector("h1", timeout=10000)
            page.wait_for_timeout(300)
        # a decision card: the Rule-of-Two meter and the explanation in Hindi
        page.goto(f"{base}/#/scenarios/email_injection")
        page.click("text=Run this scenario >> nth=0") if page.locator("text=Run this scenario").count() else None
        page.locator("text=Rule of Two").last.wait_for(state="visible", timeout=15000)   # the deciding step
        assert page.locator("text=3 of 3").count() >= 1                                # inbox + CRM + send
        page.click("text=Full explanation >> nth=-1")
        page.click("text=Read in Hindi >> nth=-1")
        page.locator("text=रोका गया").first.wait_for(state="visible", timeout=10000)
        # the CFO tier: two seats, two people
        page.request.post(f"{base}/api/demo/ap_cfo_tier")
        page.goto(f"{base}/#/approvals")
        page.wait_for_selector("text=Approve as CFO", timeout=10000)
        page.fill("#approver", "anita")
        page.click("text=Approve as CFO")
        page.wait_for_selector("text=still needs 1 × Finance Director", timeout=10000)
        page.fill("#approver", "anita")
        before = len(problems)
        page.click("text=Approve as Finance Director")
        page.wait_for_selector("text=already approved this once", timeout=10000)        # same person, second seat
        expected = [x for x in problems[before:] if "status of 403" in x]               # that refusal is the point
        if len(expected) == 1:
            problems.remove(expected[0])
        page.fill("#approver", "rahul")
        page.click("text=Approve as Finance Director")
        page.wait_for_selector("text=waiting in an undo window", timeout=10000)
        # sign-in: with auth on, the console asks for a token; signed in, it works and shows who you are
        from kavach import auth, server
        server.AUTH_SECRET = "kavach-test-secret-at-least-32-bytes-long"
        page.goto(f"{base}/#/approvals")
        page.reload()
        page.wait_for_selector("text=Sign-in is on for this server", timeout=10000)
        problems[:] = [x for x in problems if "status of 401" not in x]              # the refusals are expected
        page.click("#signin")
        page.fill("#token-in", auth.mint("anita", "cfo", secret=server.AUTH_SECRET))
        page.click("text=Sign in >> nth=-1")
        page.wait_for_selector("text=from your sign-in", timeout=10000)
        server.AUTH_SECRET = None
        b.close()
    srv.should_exit = True
    for x in problems:
        print(x)
    print("console check:", "OK" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
