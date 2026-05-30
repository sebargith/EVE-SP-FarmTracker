"""Revenue, cost, and profit calculations."""

from __future__ import annotations


def calculate_lsi_revenue(injectors: float, lsi_price: float, tax_rate: float) -> float:
    """Return net Large Skill Injector revenue after market fees/taxes."""

    return injectors * lsi_price * (1 - tax_rate)


def calculate_extractor_cost(injectors: float, extractor_unit_cost: float) -> float:
    """Return total Skill Extractor cost for the injector count."""

    return injectors * extractor_unit_cost


def calculate_training_cost(omega_cost: float, mct_cost: float) -> float:
    """Return total Omega and MCT training cost."""

    return omega_cost + mct_cost


def calculate_profit(net_revenue: float, total_cost: float) -> float:
    """Return net profit or loss."""

    return net_revenue - total_cost


def profit_per_month(profit: float, months: int) -> float:
    """Return profit normalized by calendar months."""

    if months <= 0:
        raise ValueError("months must be greater than zero")
    return profit / months
