"""Data models for local SP farm tracking."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountGroup:
    id: int
    name: str
    notes: str


@dataclass(frozen=True)
class Account:
    id: int
    group_id: int
    name: str
    omega_status: str
    omega_expires_at: str | None
    mct_slots: int
    wallet_balance: float | None
    sync_status: str
    notes: str


@dataclass(frozen=True)
class Character:
    id: int
    account_id: int
    name: str
    eve_character_id: int | None
    total_sp: int
    total_sp_updated_at: str
    training_rate_sp_min: float
    current_skill: str
    queue_ends_at: str | None
    attribute_profile: str
    implant_profile: str
    last_sync_at: str | None
    sync_status: str
    notes: str


@dataclass(frozen=True)
class ApiToken:
    id: int
    character_id: int
    eve_character_id: int
    scopes: str
    encrypted_refresh_token: str
    access_token_expires_at: str | None
    last_refresh_at: str | None
    last_sync_at: str | None
    status: str
    created_at: str
    updated_at: str
