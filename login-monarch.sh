#!/usr/bin/env bash
set -euo pipefail

# Usage: ./login-monarch.sh
#
# Run this from an interactive terminal on the machine hosting Octo Satellite.
# It prompts locally for Monarch credentials and optional MFA, replaces the
# stored session and token, validates the result, then restarts an active user
# service. Credentials are neither logged nor passed through environment variables.
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
read -r -p "Email: " email
read -r -s -p "Password: " password
printf '\n'
read -r -p "Two-factor code (leave blank if not required): " two_factor_code

printf -v login_data '%s\n%s\n%s\n' "$email" "$password" "$two_factor_code"
exec 3<<<"$login_data"
unset email password two_factor_code login_data

PYTHONPATH=src "$python" - <<'PY'
import asyncio
import sys

from monarchmoney import LoginFailedException, MonarchMoney, RequireMFAException

from octo_satellite.providers.monarch import SESSION_FILE, TOKEN_FILE, monarch_session


async def main() -> int:
    with open(3) as credentials:
        email, password, two_factor_code = credentials.read().splitlines()[:3]
    # Do not send the expired token from token.txt with a fresh login request.
    mm = MonarchMoney(session_file=str(SESSION_FILE))
    monarch_session._mm = mm

    try:
        try:
            await mm.login(email, password, use_saved_session=False)
        except RequireMFAException:
            if not two_factor_code:
                print("Monarch requires a two-factor code.", file=sys.stderr)
                return 1
            await mm.multi_factor_authenticate(email, password, two_factor_code)
    except (LoginFailedException, RequireMFAException) as error:
        print(f"Monarch rejected the login: {error}", file=sys.stderr)
        return 1

    if not mm.token:
        print("Monarch login completed without returning a token.", file=sys.stderr)
        return 1
    mm.save_session(str(SESSION_FILE))
    TOKEN_FILE.write_text(f"{mm.token}\n")
    TOKEN_FILE.chmod(0o600)

    result = await monarch_session.check_auth()
    if not result["authenticated"]:
        print("Monarch authentication validation failed.", file=sys.stderr)
        return 1

    print("Monarch authentication succeeded.")
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
