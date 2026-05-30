"""Break-even calculations for SP farming decisions."""

from __future__ import annotations


def break_even_lsi_price(total_cost: float, injectors: float, tax_rate: float) -> float:
    """Return the LSI sell price required to break even after fees/taxes."""

    if injectors <= 0:
        return 0
    if tax_rate >= 1:
        raise ValueError("tax_rate must be less than one")
    return total_cost / injectors / (1 - tax_rate)


def max_extractor_price(
    net_revenue: float, training_cost: float, injectors: float
) -> float:
    """Return the maximum extractor unit price that leaves profit at zero."""

    if injectors <= 0:
        return 0
    return (net_revenue - training_cost) / injectors


def max_omega_cost(net_revenue: float, extractor_cost: float) -> float:
    """Return the maximum total Omega/MCT cost that leaves profit at zero."""

    return net_revenue - extractor_cost
