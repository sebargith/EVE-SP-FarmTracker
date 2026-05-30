"""Skill-point training calculations."""

from __future__ import annotations


def sp_per_minute(primary: float, secondary: float) -> float:
    """Return EVE skill points trained per minute from primary/secondary attributes."""

    return primary + secondary / 2


def sp_per_month(sp_per_minute: float, days: int = 30) -> float:
    """Return skill points trained over a month-like period."""

    return sp_per_minute * 60 * 24 * days


def injectors_from_sp(sp: float, sp_per_injector: float = 500_000) -> float:
    """Return long-run injector output from skill points."""

    if sp_per_injector <= 0:
        raise ValueError("sp_per_injector must be greater than zero")
    return sp / sp_per_injector
