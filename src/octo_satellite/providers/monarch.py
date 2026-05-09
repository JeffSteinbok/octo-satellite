"""Monarch Money provider — API-based account and balance access."""

import logging
from pathlib import Path

from monarchmoney import MonarchMoney

from octo_satellite.config import settings

logger = logging.getLogger("octo_satellite.monarch")

SESSION_DIR = Path(settings.monarch_session_dir).expanduser()
SESSION_FILE = SESSION_DIR / "session.pickle"
TOKEN_FILE = SESSION_DIR / "token.txt"

# Account name patterns to exclude
EXCLUDED_PATTERNS: list[str] = []


class MonarchSession:
    """Manages a Monarch Money API session."""

    def __init__(self):
        self._mm: MonarchMoney | None = None

    def _load_token(self) -> str | None:
        """Load token from token.txt file."""
        if TOKEN_FILE.exists():
            raw = TOKEN_FILE.read_text().strip()
            # Handle "authorization: Token <hex>" or "Token <hex>" or bare hex
            if "Token " in raw:
                return raw.split("Token ")[-1].strip()
            return raw
        return None

    def _get_client(self) -> MonarchMoney:
        """Get or create the Monarch Money client with saved session."""
        if self._mm is None:
            SESSION_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
            token = self._load_token()
            self._mm = MonarchMoney(session_file=str(SESSION_FILE), token=token)
            if token:
                self._mm.save_session(str(SESSION_FILE))
        return self._mm

    def _reload_client(self) -> MonarchMoney:
        """Force reload the client (e.g. after token update)."""
        self._mm = None
        return self._get_client()

    async def login(self) -> bool:
        """Interactive login — prompts for email, password, and MFA."""
        mm = self._get_client()
        try:
            await mm.interactive_login()
            # Lock down session file
            if SESSION_FILE.exists():
                SESSION_FILE.chmod(0o600)
            return True
        except Exception as e:
            logger.error(f"Monarch login failed: {e}")
            return False

    async def check_auth(self) -> dict:
        """Verify the saved session is still valid."""
        mm = self._reload_client()
        try:
            await mm.get_accounts()
            return {"authenticated": True}
        except Exception as e:
            logger.warning(f"Monarch auth check failed: {e}")
            return {"authenticated": False}

    async def get_sync_status(self) -> dict | None:
        """Get sync status for all active accounts."""
        mm = self._get_client()
        try:
            raw = await mm.get_accounts()
        except Exception as e:
            logger.error(f"Monarch get_sync_status failed: {e}")
            return None

        accounts = []
        for account in raw.get("accounts", []):
            is_active = not account.get("isHidden", False) and not account.get("deactivatedAt")
            if not is_active:
                continue

            credential = account.get("credential") or {}
            institution = credential.get("institution") or {}

            accounts.append({
                "id": account.get("id"),
                "name": account.get("displayName", ""),
                "institution": institution.get("name"),
                "institution_status": institution.get("status"),
                "last_synced": account.get("displayLastUpdatedAt"),
                "sync_disabled": account.get("syncDisabled", False),
                "update_required": credential.get("updateRequired", False),
                "disconnected_at": credential.get("disconnectedFromDataProviderAt"),
            })

        accounts.sort(key=lambda a: a["last_synced"] or "", reverse=True)
        return {"accounts": accounts}

    async def refresh_accounts(self) -> dict | None:
        """Trigger an account refresh (non-blocking — does not wait for completion)."""
        mm = self._get_client()
        try:
            raw = await mm.get_accounts()
            account_ids = [a["id"] for a in raw.get("accounts", []) if not a.get("syncDisabled")]
            await mm.request_accounts_refresh(account_ids)
            return {"refresh_requested": True, "account_count": len(account_ids)}
        except Exception as e:
            logger.error(f"Monarch refresh_accounts failed: {e}")
            return None

    async def get_accounts(self) -> dict | None:
        """Fetch accounts grouped by type with balances."""
        mm = self._get_client()
        try:
            raw = await mm.get_accounts()
        except Exception as e:
            logger.error(f"Monarch get_accounts failed: {e}")
            return None

        # Parse and group accounts
        accounts_by_type: dict[str, list[dict]] = {}

        for account in raw.get("accounts", []):
            name = account.get("displayName", "")

            # Skip excluded accounts
            if any(pat.lower() in name.lower() for pat in EXCLUDED_PATTERNS):
                continue

            account_type = account.get("type", {}).get("display", "Other")
            balance = account.get("currentBalance", 0)
            is_active = not account.get("isHidden", False) and not account.get("deactivatedAt")

            if not is_active:
                continue

            entry = {
                "name": name,
                "balance": balance,
                "institution": account.get("institution", {}).get("name", None)
                if account.get("institution")
                else None,
                "last_updated": account.get("updatedAt"),
            }

            if account_type not in accounts_by_type:
                accounts_by_type[account_type] = []
            accounts_by_type[account_type].append(entry)

        # Sort accounts within each type by balance descending
        for acct_type in accounts_by_type:
            accounts_by_type[acct_type].sort(key=lambda a: a["balance"] or 0, reverse=True)

        # Calculate totals per type
        summary = {}
        for acct_type, accounts in accounts_by_type.items():
            summary[acct_type] = {
                "total": sum(a["balance"] or 0 for a in accounts),
                "accounts": accounts,
            }

        return summary

    async def get_net_worth(self) -> dict | None:
        """Get net worth from Monarch's aggregate snapshots.

        Returns the most recent net worth value as calculated by Monarch
        (respects includeInNetWorth account settings).
        """
        from datetime import date, timedelta

        mm = self._get_client()
        try:
            today = date.today()
            start = today - timedelta(days=1)
            result = await mm.get_aggregate_snapshots(
                start_date=start.isoformat(), end_date=today.isoformat()
            )
            snapshots = result.get("aggregateSnapshots", [])
            if not snapshots:
                return None
            # Use the most recent snapshot
            latest = snapshots[-1]
            return {
                "net_worth": latest["balance"],
                "as_of": latest["date"],
            }
        except Exception as e:
            logger.error(f"Monarch get_net_worth failed: {e}")
            return None

    async def get_spending(self, months: int = 3) -> dict | None:
        """Get spending trends via cashflow APIs.

        Returns overall summary (income/expenses/savings) and breakdown by category.
        """
        from datetime import date, timedelta

        mm = self._get_client()
        try:
            today = date.today()
            start = today - timedelta(days=months * 30)
            start_str = start.isoformat()
            end_str = today.isoformat()

            summary_result = await mm.get_cashflow_summary(start_date=start_str, end_date=end_str)
            cashflow_result = await mm.get_cashflow(start_date=start_str, end_date=end_str)

            # Parse summary — nested under summary[0].summary
            totals = {}
            summaries = summary_result.get("summary", [])
            if summaries:
                s = summaries[0].get("summary", {})
                totals = {
                    "income": s.get("sumIncome", 0),
                    "expenses": s.get("sumExpense", 0),
                    "savings": s.get("savings", 0),
                    "savings_rate": s.get("savingsRate", 0),
                }

            # Parse per-category breakdown
            income_categories = []
            expense_categories = []
            for entry in cashflow_result.get("byCategory", []):
                cat = entry.get("groupBy", {}).get("category", {})
                cat_name = cat.get("name", "Unknown")
                cat_type = cat.get("group", {}).get("type", "expense")
                amount = entry.get("summary", {}).get("sum", 0)

                item = {"category": cat_name, "amount": amount}
                if cat_type == "income":
                    income_categories.append(item)
                else:
                    expense_categories.append(item)

            # Sort by absolute amount descending
            income_categories.sort(key=lambda x: abs(x["amount"]), reverse=True)
            expense_categories.sort(key=lambda x: abs(x["amount"]), reverse=True)

            return {
                "period_start": start_str,
                "period_end": end_str,
                "totals": totals,
                "income_by_category": income_categories,
                "expenses_by_category": expense_categories,
            }
        except Exception as e:
            logger.error(f"Monarch get_spending failed: {e}")
            return None


# Singleton instance
monarch_session = MonarchSession()
