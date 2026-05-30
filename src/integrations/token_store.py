"""Local refresh-token protection.

Refresh tokens are long-lived credentials. On Windows this module protects them
with DPAPI so the ciphertext is bound to the current Windows user profile.
"""

from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes


class TokenStoreError(RuntimeError):
    """Raised when a token cannot be protected or restored."""


def encrypt_refresh_token(refresh_token: str) -> str:
    """Return a storage-safe encrypted token string."""

    if os.name == "nt":
        return "dpapi:" + base64.urlsafe_b64encode(
            _crypt_protect(refresh_token.encode("utf-8"))
        ).decode("ascii")

    if os.environ.get("EVE_ALLOW_UNENCRYPTED_TOKENS") == "1":
        return "plain:" + base64.urlsafe_b64encode(refresh_token.encode("utf-8")).decode("ascii")

    raise TokenStoreError(
        "Encrypted token storage is only implemented with Windows DPAPI. "
        "Add a secure token backend before storing EVE refresh tokens here."
    )


def decrypt_refresh_token(encrypted_refresh_token: str) -> str:
    """Restore a refresh token previously produced by encrypt_refresh_token."""

    if encrypted_refresh_token.startswith("dpapi:"):
        if os.name != "nt":
            raise TokenStoreError("DPAPI token can only be decrypted on Windows.")
        data = base64.urlsafe_b64decode(encrypted_refresh_token.removeprefix("dpapi:"))
        return _crypt_unprotect(data).decode("utf-8")

    if encrypted_refresh_token.startswith("plain:"):
        if os.environ.get("EVE_ALLOW_UNENCRYPTED_TOKENS") != "1":
            raise TokenStoreError("Refusing to read unencrypted token storage.")
        data = base64.urlsafe_b64decode(encrypted_refresh_token.removeprefix("plain:"))
        return data.decode("utf-8")

    raise TokenStoreError("Unsupported token storage format.")


if os.name == "nt":

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]


def _crypt_protect(data: bytes) -> bytes:
    buffer = ctypes.create_string_buffer(data)
    input_blob = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    output_blob = _DATA_BLOB()

    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(output_blob),
    ):
        raise TokenStoreError("Windows DPAPI failed to protect the refresh token.")

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def _crypt_unprotect(data: bytes) -> bytes:
    buffer = ctypes.create_string_buffer(data)
    input_blob = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    output_blob = _DATA_BLOB()

    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(output_blob),
    ):
        raise TokenStoreError("Windows DPAPI failed to restore the refresh token.")

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)
