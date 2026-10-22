#!/usr/bin/env bash
set -euo pipefail

# Usage: ./login-amazon.sh
#
# Run this from an interactive terminal (SSH is fine) on the machine hosting Octo
# Satellite. It signs in to Amazon in a headless browser, starting from the saved
# session so Amazon recognizes the device, and prompts locally for the password and
# any two-factor code. It then saves the session and restarts the service so it
# picks up the new session. Credentials are neither logged nor passed through
# environment variables.
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    printf 'Usage: %s\n' "$(basename "$0")"
    exit 0
fi

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python="$project_dir/.venv/bin/python"

if [[ ! -x "$python" ]]; then
    printf 'Missing virtual environment Python: %s\n' "$python" >&2
    exit 1
fi

cd "$project_dir"
PYTHONPATH=src "$python" - <<'PY'
import asyncio
import getpass
import sys
import time

from playwright.async_api import Error as PlaywrightError

from octo_satellite.providers.amazon import AUTH_CHECK_URL, SESSION_DIR, amazon_session

TIMEOUT_SECONDS = 300


def prompt(text: str) -> str:
    # stdin is this heredoc, so read from the terminal directly
    with open("/dev/tty") as tty:
        sys.stdout.write(text)
        sys.stdout.flush()
        return tty.readline().strip()


async def visible(page, selector: str) -> bool:
    loc = page.locator(selector)
    return await loc.count() > 0 and await loc.first.is_visible()


async def step(page, announced: set[str]) -> bool:
    """Advance the sign-in flow by one screen. Returns False to give up."""
    if await visible(page, "#auth-captcha-image") or await visible(page, "#captchacharacters"):
        print("Amazon is asking for a captcha; headless login can't continue.", file=sys.stderr)
        return False

    for email_field in ("#ap_email", "#ap_email_login"):
        if await visible(page, email_field):
            await page.fill(email_field, prompt("Amazon email: "))
            await page.click("#continue")
            return True

    if await visible(page, "#ap_password"):
        await page.fill("#ap_password", getpass.getpass("Amazon password: "))
        if await visible(page, "input[name=rememberMe]"):
            await page.check("input[name=rememberMe]")
        await page.click("#signInSubmit")
    elif await visible(page, "#auth-mfa-otpcode"):
        await page.fill("#auth-mfa-otpcode", prompt("Two-factor code: "))
        if await visible(page, "#auth-mfa-remember-device"):
            await page.check("#auth-mfa-remember-device")
        await page.click("#auth-signin-button")
    elif "ap/cvf" in page.url and "approval" not in announced:
        print("Amazon wants approval — approve the sign-in on your phone or email.")
        announced.add("approval")
    return True


async def main() -> int:
    ctx = await amazon_session.start(headless=True)
    page = await ctx.new_page()
    await page.goto(AUTH_CHECK_URL, wait_until="domcontentloaded")

    deadline = time.monotonic() + TIMEOUT_SECONDS
    announced: set[str] = set()
    while time.monotonic() < deadline:
        await page.wait_for_timeout(1500)

        if "ap/signin" not in page.url and "your-orders" in page.url:
            break

        try:
            if not await step(page, announced):
                break
        except PlaywrightError:
            # Page navigated mid-check; look again on the next pass
            continue

    authenticated = "ap/signin" not in page.url and "your-orders" in page.url
    if authenticated:
        await amazon_session.save_session()
    else:
        shot = SESSION_DIR / "login-failure.png"
        await page.screenshot(path=str(shot))
        shot.chmod(0o600)
        print(f"Amazon login did not complete (last page: {page.url.split('?')[0]}).", file=sys.stderr)
        print(f"Screenshot: {shot}", file=sys.stderr)
    await page.close()
    await amazon_session.close()
    if not authenticated:
        return 1

    result = await amazon_session.check_auth()
    await amazon_session.close()
    if not result["authenticated"]:
        print("Amazon authentication validation failed.", file=sys.stderr)
        return 1

    print(f"Amazon authentication succeeded ({result['name']}).")
    return 0


raise SystemExit(asyncio.run(main()))
PY

launchd_target="system/com.jeffsteinbok.octo-satellite"
if systemctl --user --quiet is-active octo-satellite.service 2>/dev/null; then
    systemctl --user restart octo-satellite.service
    printf 'Restarted octo-satellite.service.\n'
elif [[ -f /Library/LaunchDaemons/com.jeffsteinbok.octo-satellite.plist ]]; then
    printf 'Restarting the service (sudo will ask for your Mac password)...\n'
    sudo launchctl kickstart -k "$launchd_target"
    printf 'Restarted %s.\n' "$launchd_target"
else
    printf 'Octo Satellite service restart skipped.\n'
fi
