import pytest

from src.calculations.break_even import (
    break_even_lsi_price,
    max_extractor_price,
    max_omega_cost,
)


def test_break_even_lsi_price() -> None:
    assert break_even_lsi_price(5_157_859_200, 4.088, 0.05) == pytest.approx(
        1_328_112_884.9521062
    )


def test_break_even_lsi_price_returns_zero_without_injectors() -> None:
    assert break_even_lsi_price(100, 0, 0.05) == 0


def test_max_extractor_price() -> None:
    assert max_extractor_price(2_923_962_440, 2_405_000_000, 4.088) == pytest.approx(
        126_947_759.295499
    )


def test_max_omega_cost() -> None:
    assert max_omega_cost(2_923_962_440, 2_752_859_200) == 171_103_240
