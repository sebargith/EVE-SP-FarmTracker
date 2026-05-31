"""Fetch ESI assets with the app's stored per-character authorization."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from src.data.repositories import store_api_token
from src.integrations.esi_auth import EsiAuthenticatedClient
from src.integrations.sso import SsoConfig, TokenResponse, refresh_access_token
from src.integrations.token_store import decrypt_refresh_token, encrypt_refresh_token


ASSETS_SCOPE = "esi-assets.read_assets.v1"


class AssetClient(Protocol):
    def get_assets(self, character_id: int) -> list[dict[str, Any]]: ...

    def close(self) -> None: ...


def fetch_assets_from_stored_authorization(
    connection: sqlite3.Connection,
    *,
    token_row: dict[str, Any],
    config: SsoConfig,
    refresh: Callable[..., TokenResponse] = refresh_access_token,
    client_factory: Callable[[str], AssetClient] = EsiAuthenticatedClient,
) -> list[dict[str, Any]]:
    """Refresh one stored token and fetch its character assets."""

    scopes = tuple(str(token_row["scopes"]).split())
    if ASSETS_SCOPE not in scopes:
        raise ValueError(f"Missing scope: {ASSETS_SCOPE}")

    token_response = refresh(
        config,
        refresh_token=decrypt_refresh_token(str(token_row["encrypted_refresh_token"])),
    )
    store_api_token(
        connection,
        character_id=int(token_row["character_id"]),
        eve_character_id=int(token_row["eve_character_id"]),
        scopes=scopes,
        encrypted_refresh_token=encrypt_refresh_token(token_response.refresh_token),
        access_token_expires_at=_expires_at_iso(token_response.expires_in),
        status=str(token_row["status"]),
    )
    client = client_factory(token_response.access_token)
    try:
        return client.get_assets(int(token_row["eve_character_id"]))
    finally:
        client.close()


def _expires_at_iso(expires_in: int) -> str:
    return datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + int(expires_in),
        tz=timezone.utc,
    ).isoformat()
