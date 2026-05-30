"""Display formatting helpers."""

from __future__ import annotations


def format_isk(value: float) -> str:
    absolute = abs(value)
    sign = "-" if value < 0 else ""
    if absolute >= 1_000_000_000:
        return f"{sign}{absolute / 1_000_000_000:,.2f}B ISK"
    if absolute >= 1_000_000:
        return f"{sign}{absolute / 1_000_000:,.1f}M ISK"
    return f"{sign}{absolute:,.0f} ISK"


def format_number(value: float) -> str:
    return f"{value:,.2f}"


def metric_delta(value: float) -> str:
    return "profitable" if value > 0 else "loss"
