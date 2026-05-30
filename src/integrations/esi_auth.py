"""Authenticated ESI client for character tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


ESI_BASE_URL = "https://esi.evetech.net/latest"
DEFAULT_USER_AGENT = "EVE SP Farm Planner/0.1 local"


@dataclass(frozen=True)
class EsiCharacterData:
    skills: dict[str, Any] | None
    skill_queue: list[dict[str, Any]]
    attributes: dict[str, Any] | None
    implants: list[int]
    wallet_balance: float | None = None
    assets: list[dict[str, Any]] | None = None


class EsiAuthenticatedClient:
    """Small authenticated ESI client for the endpoints this app needs."""

    def __init__(
        self,
        access_token: str,
        *,
        base_url: str = ESI_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        client: httpx.Client | None = None,
    ) -> None:
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=20)
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": user_agent,
            "X-Compatibility-Date": esi_compatibility_date(),
        }

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def get_character_data(
        self,
        character_id: int,
        *,
        include_wallet: bool = False,
        include_assets: bool = False,
    ) -> EsiCharacterData:
        return EsiCharacterData(
            skills=self.get_character_skills(character_id),
            skill_queue=self.get_skill_queue(character_id),
            attributes=self.get_attributes(character_id),
            implants=self.get_implants(character_id),
            wallet_balance=self.get_wallet_balance(character_id) if include_wallet else None,
            assets=self.get_assets(character_id) if include_assets else None,
        )

    def get_character_skills(self, character_id: int) -> dict[str, Any]:
        return self._get(f"/characters/{character_id}/skills/")

    def get_skill_queue(self, character_id: int) -> list[dict[str, Any]]:
        payload = self._get(f"/characters/{character_id}/skillqueue/")
        return list(payload) if isinstance(payload, list) else []

    def get_attributes(self, character_id: int) -> dict[str, Any]:
        return self._get(f"/characters/{character_id}/attributes/")

    def get_implants(self, character_id: int) -> list[int]:
        payload = self._get(f"/characters/{character_id}/implants/")
        return [int(item) for item in payload] if isinstance(payload, list) else []

    def get_wallet_balance(self, character_id: int) -> float:
        return float(self._get(f"/characters/{character_id}/wallet/"))

    def get_assets(self, character_id: int) -> list[dict[str, Any]]:
        return self._get_paginated(f"/characters/{character_id}/assets/")

    def _get(self, path: str) -> Any:
        response = self.client.get(
            f"{self.base_url}{path}",
            headers=self.headers,
            params={"datasource": "tranquility"},
        )
        response.raise_for_status()
        return response.json()

    def _get_paginated(self, path: str) -> list[dict[str, Any]]:
        first_response = self.client.get(
            f"{self.base_url}{path}",
            headers=self.headers,
            params={"datasource": "tranquility", "page": 1},
        )
        first_response.raise_for_status()
        results = list(first_response.json())
        pages = int(first_response.headers.get("X-Pages", "1"))
        for page in range(2, pages + 1):
            response = self.client.get(
                f"{self.base_url}{path}",
                headers=self.headers,
                params={"datasource": "tranquility", "page": page},
            )
            response.raise_for_status()
            results.extend(response.json())
        return results


def esi_compatibility_date(now: datetime | None = None) -> str:
    """Return a non-future ESI compatibility date."""

    current = now or datetime.now(timezone.utc)
    return (current - timedelta(hours=11)).date().isoformat()
