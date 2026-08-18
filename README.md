# 🐙🛰️ Octo Satlellite

> **⚠️ Security Recommendations**
>
> - **Run this in a separate user account** from OpenClaw. This service holds real credentials and should be isolated.
> - **Restrict file permissions** on config files containing secrets:
>   ```bash
>   chmod 600 .env
>   chmod 700 ~/.config/octo-satellite
>   chmod 600 ~/.config/octo-satellite/monarch/token.txt
>   ```
> - **Localhost-only mode** is enabled by default (`OCTO_LOCALHOST_ONLY=true`). This rejects any request from a non-loopback IP with a 403, even if the server is accidentally bound to `0.0.0.0` or a real network interface. Do not disable this in production.

## About

Octo Satellite is a local secrets broker that sits between [OpenClaw](https://github.com/JeffSteinbok/openclaw) and credentialed services. It exposes a REST API on `localhost` so OpenClaw can access sensitive data without directly holding credentials.

OpenClaw is an AI agent that manages household tasks — but it shouldn't hold passwords or session cookies directly. Octo Satellite runs as a separate service, handling authentication and credential storage so OpenClaw can request data through a safe, audited API boundary.

## Providers

### Amazon (`/amazon`)
Browser-automated via Playwright. Requires an interactive login session.

| Endpoint | Method | Description |
|---|---|---|
| `/amazon/health` | GET | Check if Amazon session is authenticated |
| `/amazon/login` | POST | Interactive browser login |
| `/amazon/orders` | GET | List orders with pagination (`?page=N`) |
| `/amazon/orders/{order_id}` | GET | Order detail with tracking info |
| `/amazon/cart` | GET | View cart contents |
| `/amazon/cart` | POST | Add item to cart (`?asin=B0...`) |
| `/amazon/cart/{item_id}` | DELETE | Remove item from cart |
| `/amazon/search` | GET | Search products (`?q=...&page=N`) |
| `/amazon/items/{asin}` | GET | Product details by ASIN |

### Monarch Money (`/monarch`)
API-based via [monarchmoneycommunity](https://github.com/bradleyseanf/monarchmoneycommunity).

| Endpoint | Method | Description |
|---|---|---|
| `/monarch/health` | GET | Check auth status (also reloads token) |
| `/monarch/login` | POST | Interactive login |
| `/monarch/sync-status` | GET | Sync status per account — last synced, institution health |
| `/monarch/refresh` | POST | Trigger account refresh (fire-and-forget) |
| `/monarch/accounts` | GET | Accounts grouped by type with balances |
| `/monarch/net-worth` | GET | Net worth from Monarch's aggregate snapshots (`?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` for daily history) |
| `/monarch/spending` | GET | Spending trends: income, expenses, savings (`?months=3` or `?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`) |
| `/monarch/categories` | GET | List transaction categories (id, name, group) for use as filters |
| `/monarch/merchants` | GET | Merchant spend breakdown — aggregate totals only, no transactions (`?category=Travel & Lifestyle&start_date=...&end_date=...&limit=N`) |
| `/monarch/investments` | GET | Investment account positions/holdings (`?account_id=N`) |

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Key settings (all prefixed with `OCTO_`):

| Variable | Default | Description |
|---|---|---|
| `OCTO_SHARED_SECRET` | _(none)_ | Shared secret for Bearer auth |
| `OCTO_PORT` | `9000` | Production port (auth enforced) |
| `OCTO_DEV_PORT` | `9001` | Dev port (auth skipped) |
| `OCTO_HOST` | `127.0.0.1` | Bind address (localhost only) |
| `OCTO_LOCALHOST_ONLY` | `true` | Reject non-loopback clients (defense-in-depth) |

Environment variables can be referenced in `.env` with `${VAR}` syntax.

### Monarch Money Token

Place your Monarch Money API token in:
```
~/.config/octo-satellite/monarch/token.txt
```

The file can contain the bare token, `Token <hex>`, or the full `authorization: Token <hex>` header.

## Running

```bash
# Production (port 9000, auth required)
python src/octo_satellite/main.py

# Dev (port 9001, no auth)
OCTO_PORT=9001 python src/octo_satellite/main.py
```

## Auth

On the production port, all requests require either:
- Header: `Authorization: Bearer <shared_secret>`
- Query param: `?token=<shared_secret>`

Auth is skipped on the dev port.

## Development

```bash
# Run tests
pytest

# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/
```

## Architecture

- **FastAPI** app with provider-segmented routing
- **Playwright** for Amazon browser automation (single session with asyncio lock)
- **monarchmoneycommunity** for Monarch Money API access
- **Session heartbeat** every 3 hours to keep sessions alive
- **Audit logging** (JSONL) for all API calls
- All sessions stored in `~/.config/octo-satellite/` with `0600` permissions
