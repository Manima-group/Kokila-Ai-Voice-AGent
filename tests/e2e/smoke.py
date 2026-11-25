"""Browser smoke test: register -> sign in -> text turn -> Super Admin upgrades plan -> voice controls.

Usage (API on :8000 with KOKILA_REASONING_PROVIDER=dev_mock, web on :3000):
    python tests/e2e/smoke.py --chrome /usr/bin/google-chrome --out /tmp/kokila-e2e
Requires: playwright, pyotp, httpx, and psql access to promote the bootstrap admin (dev only).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import uuid
from pathlib import Path

import httpx
import pyotp
from playwright.sync_api import expect, sync_playwright

WEB = os.environ.get("KOKILA_WEB", "http://localhost:3000")
API = os.environ.get("KOKILA_API", "http://localhost:8000")
PW = "correct-horse-battery-staple"


def make_admin() -> tuple[str, str]:
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    httpx.post(f"{API}/v1/auth/register", json={"email": email, "password": PW, "display_name": "Manima Admin"})
    subprocess.run(["psql", os.environ.get("KOKILA_OWNER_DSN", "postgresql://kokila_owner:kokila_owner_dev@localhost/kokila"),
                    "-qc", f"update users set platform_role='super_admin' where email='{email}'"], check=True)
    tok = httpx.post(f"{API}/v1/auth/login", json={"email": email, "password": PW}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    secret = httpx.post(f"{API}/v1/auth/mfa/enroll", headers=h).json()["secret"]
    assert httpx.post(f"{API}/v1/auth/mfa/verify", headers=h, json={"code": pyotp.TOTP(secret).now()}).status_code == 204
    return email, secret


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome", default=None)
    ap.add_argument("--out", default="/tmp/kokila-e2e")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    run = uuid.uuid4().hex[:6]
    user_email = f"user-{run}@example.com"
    admin_email, secret = make_admin()

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chrome, args=[
            "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        console_errors: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)

        page.goto(f"{WEB}/register")
        page.fill("#display_name", f"Sai {run}")
        page.fill("#email", user_email)
        page.fill("#password", PW)
        page.click("text=Create account")
        page.click("text=Go to sign in")
        page.fill("#email", user_email)
        page.fill("#password", PW)
        page.click("button:has-text('Sign in')")
        page.wait_for_url("**/assistant")
        expect(page.get_by_text("Voice isn't included in your current plan")).to_be_visible()
        page.fill("input[aria-label=Message]", "నమస్తే Kokila, what can you do?")
        page.click("button:has-text('Send')")
        expect(page.get_by_text("[dev mock] Kokila received").first).to_be_visible(timeout=15_000)
        page.screenshot(path=str(out / "01-assistant-text.png"), full_page=True)

        admin = browser.new_context(viewport={"width": 1280, "height": 1000}).new_page()
        admin.goto(f"{WEB}/login")
        admin.fill("#email", admin_email)
        admin.fill("#password", PW)
        admin.check("text=Manima platform administration")
        admin.fill("#otp", pyotp.TOTP(secret).now())
        admin.click("button:has-text('Sign in')")
        admin.wait_for_url("**/admin")
        admin.click(f"text=Sai {run}'s workspace")
        expect(admin.get_by_text("Capability matrix")).to_be_visible()
        admin.on("dialog", lambda d: d.accept())
        admin.fill("#reason", "e2e upgrade to Plus")
        admin.select_option("select[aria-label='Change plan']", "assistant-plus")
        expect(admin.get_by_text("Plan changed to assistant-plus")).to_be_visible()
        admin.screenshot(path=str(out / "02-admin-matrix.png"), full_page=True)

        page.reload()
        expect(page.get_by_role("button", name="🎙️ Unmute microphone")).to_be_visible(timeout=10_000)
        expect(page.get_by_text("microphone muted")).to_be_visible()
        page.click("button:has-text('Unmute microphone')")
        expect(page.get_by_role("button", name="🎙️ Mute microphone")).to_be_visible()
        page.click("button:has-text('Mute all')")
        expect(page.get_by_role("button", name="🎙️ Unmute microphone")).to_be_visible()
        page.fill("input[aria-label=Message]", "remember that I like filter coffee")
        page.click("button:has-text('Send')")
        expect(page.get_by_text("Approval required")).to_be_visible(timeout=15_000)
        page.screenshot(path=str(out / "03-approval.png"), full_page=True)
        page.click("button:has-text('Approve')")
        expect(page.get_by_text('"succeeded"').first).to_be_visible(timeout=10_000)
        page.goto(f"{WEB}/memory")
        expect(page.get_by_text("I like filter coffee")).to_be_visible()
        page.screenshot(path=str(out / "04-memory.png"), full_page=True)
        browser.close()
    unexpected = [e for e in console_errors if "favicon" not in e]
    print("console errors:", unexpected or "none")
    print("E2E SMOKE PASSED; screenshots in", out)


if __name__ == "__main__":
    main()
