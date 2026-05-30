import pytest

from src.calculations.profitability import (
    calculate_extractor_cost,
    calculate_lsi_revenue,
    calculate_profit,
    calculate_training_cost,
    profit_per_month,
)


def test_lsi_revenue_after_taxes() -> None:
    assert calculate_lsi_revenue(4, 752_900_000, 0.05) == pytest.approx(
        2_861_020_000
    )


def test_extractor_cost() -> None:
    assert calculate_extractor_cost(4.088, 673_400_000) == pytest.approx(
        2_752_859_200
    )


def test_training_cost() -> None:
    assert calculate_training_cost(2_405_000_000, 0) == 2_405_000_000


def test_profit_loss() -> None:
    assert calculate_profit(2_923_962_440, 5_157_859_200) == pytest.approx(
        -2_233_896_760
    )


def test_profit_per_month() -> None:
    assert profit_per_month(-2_233_896_760, 1) == -2_233_896_760


def test_profit_per_month_rejects_zero_months() -> None:
    with pytest.raises(ValueError):
        profit_per_month(100, 0)
