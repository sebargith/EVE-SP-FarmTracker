"""EVE SSO OAuth helpers."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient


AUTHORIZATION_ENDPOINT = "https://login.eveonline.com/v2/oauth/authorize"
TOKEN_ENDPOINT = "https://login.eveonline.com/v2/oauth/token"
METADATA_URL = "https://login.eveonline.com/.well-known/oauth-authorization-server"
ACCEPTED_ISSUERS = ("logineveonline.com", "https://login.eveonline.com")
EXPECTED_AUDIENCE = "EVE Online"
DEFAULT_SCOPES = (
    "esi-skills.read_skills.v1",
    "esi-skills.read_skillqueue.v1",
    "esi-clones.read_implants.v1",
)


@dataclass(frozen=True)
class SsoConfig:
    client_id: str
    callback_url: str
    scopes: tuple[str, ...] = DEFAULT_SCOPES

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.callback_url)


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str

    @property
    def expires_at_unix(self) -> int:
        return int(time.time()) + int(self.expires_in)


def load_sso_config(
    *,
    env: dict[str, str] | None = None,
    env_path: str | Path = ".env",
) -> SsoConfig:
    """Load SSO config from environment variables and an optional .env file."""

    values = _read_env_file(env_path)
    values.update(env or os.environ)
    scopes = tuple(
        scope
        for scope in values.get("EVE_SCOPES", " ".join(DEFAULT_SCOPES)).split()
        if scope.strip()
    )
    return SsoConfig(
        client_id=values.get("EVE_CLIENT_ID", "").strip(),
        callback_url=values.get("EVE_CALLBACK_URL", "http://localhost:8766").strip(),
        scopes=scopes or DEFAULT_SCOPES,
    )


def generate_pkce_pair() -> tuple[str, str]:
    """Create a PKCE code verifier and S256 challenge."""

    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def generate_state() -> str:
    return secrets.token_urlsafe(24)


def build_authorization_url(
    config: SsoConfig,
    *,
    state: str,
    code_challenge: str,
    authorization_endpoint: str = AUTHORIZATION_ENDPOINT,
) -> str:
    """Build an EVE SSO authorization URL for the configured scopes."""

    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "redirect_uri": config.callback_url,
            "client_id": config.client_id,
            "scope": " ".join(config.scopes),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    return f"{authorization_endpoint}?{query}"


def exchange_authorization_code(
    config: SsoConfig,
    *,
    authorization_code: str,
    code_verifier: str,
    client: httpx.Client | None = None,
) -> TokenResponse:
    """Exchange an authorization code for access and refresh tokens."""

    close_client = client is None
    http_client = client or httpx.Client(timeout=20)
    try:
        response = http_client.post(
            TOKEN_ENDPOINT,
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "client_id": config.client_id,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return token_response_from_payload(response.json())
    finally:
        if close_client:
            http_client.close()


def refresh_access_token(
    config: SsoConfig,
    *,
    refresh_token: str,
    client: httpx.Client | None = None,
) -> TokenResponse:
    """Refresh an access token using a stored refresh token."""

    close_client = client is None
    http_client = client or httpx.Client(timeout=20)
    try:
        response = http_client.post(
            TOKEN_ENDPOINT,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": config.client_id,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return token_response_from_payload(response.json())
    finally:
        if close_client:
            http_client.close()


def token_response_from_payload(payload: dict[str, Any]) -> TokenResponse:
    return TokenResponse(
        access_token=str(payload["access_token"]),
        refresh_token=str(payload["refresh_token"]),
        expires_in=int(payload.get("expires_in", 0)),
        token_type=str(payload.get("token_type", "Bearer")),
    )


def validate_access_token(
    access_token: str,
    *,
    client_id: str,
    metadata_url: str = METADATA_URL,
) -> dict[str, Any]:
    """Validate an EVE access token and return verified JWT claims."""

    metadata = httpx.get(metadata_url, timeout=20).json()
    jwks_client = PyJWKClient(str(metadata["jwks_uri"]))
    signing_key = jwks_client.get_signing_key_from_jwt(access_token)
    claims = jwt.decode(
        access_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=EXPECTED_AUDIENCE,
        issuer=ACCEPTED_ISSUERS,
    )
    audience = claims.get("aud", [])
    if isinstance(audience, str):
        audience = [audience]
    if client_id not in audience:
        raise ValueError("Access token audience does not include this EVE client ID.")
    return claims


def decode_unverified_claims(access_token: str) -> dict[str, Any]:
    """Decode JWT claims without signature validation.

    This is used only as a fallback for test doubles and diagnostics. Production
    auth flow should prefer validate_access_token().
    """

    return jwt.decode(access_token, options={"verify_signature": False})


def character_id_from_claims(claims: dict[str, Any]) -> int:
    subject = str(claims.get("sub", ""))
    prefix = "CHARACTER:EVE:"
    if not subject.startswith(prefix):
        raise ValueError("EVE SSO token subject does not contain a character ID.")
    return int(subject.removeprefix(prefix))


def scopes_from_claims(claims: dict[str, Any]) -> tuple[str, ...]:
    scopes = claims.get("scp", [])
    if isinstance(scopes, str):
        return tuple(scopes.split())
    return tuple(str(scope) for scope in scopes)


def _read_env_file(env_path: str | Path) -> dict[str, str]:
    path = Path(env_path)
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def fake_jwt_for_tests(claims: dict[str, Any]) -> str:
    """Build an unsigned JWT-shaped token for local tests."""

    header = {"typ": "JWT", "alg": "none"}
    return ".".join(
        [
            _json_b64(header),
            _json_b64(claims),
            "",
        ]
    )


def _json_b64(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")
