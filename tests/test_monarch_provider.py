"""Tests for Monarch provider authentication."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from octo_satellite.providers import monarch


@pytest.mark.asyncio
async def test_login_replaces_expired_credentials(monkeypatch, tmp_path):
    """Explicit re-login must not reuse the persisted token or session."""
    session_file = tmp_path / "session.pickle"
    token_file = tmp_path / "token.txt"
    monkeypatch.setattr(monarch, "SESSION_FILE", session_file)
    monkeypatch.setattr(monarch, "TOKEN_FILE", token_file)

    client = MagicMock()
    client.token = "renewed-token"
    client.interactive_login = AsyncMock()

    with patch.object(monarch, "MonarchMoney", return_value=client) as client_type:
        session = monarch.MonarchSession()

        assert await session.login() is True

    client_type.assert_called_once_with(session_file=str(session_file))
    client.interactive_login.assert_awaited_once_with(use_saved_session=False)
    assert token_file.read_text() == "renewed-token\n"
    assert token_file.stat().st_mode & 0o777 == 0o600
