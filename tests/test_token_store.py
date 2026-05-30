import os

from src.integrations.token_store import decrypt_refresh_token, encrypt_refresh_token


def test_refresh_token_round_trip(monkeypatch) -> None:
    if os.name != "nt":
        monkeypatch.setenv("EVE_ALLOW_UNENCRYPTED_TOKENS", "1")

    encrypted = encrypt_refresh_token("refresh-token-value")

    assert encrypted != "refresh-token-value"
    assert decrypt_refresh_token(encrypted) == "refresh-token-value"
