import pytest

from src.calculations.sp_training import (
    injectors_from_sp,
    sp_per_minute,
    sp_per_month,
)


def test_optimized_sp_per_minute() -> None:
    assert sp_per_minute(primary=32, secondary=26) == 45


def test_optimized_monthly_sp_per_queue() -> None:
    assert sp_per_month(45, days=30) == 1_944_000


def test_injectors_from_sp_supports_fractional_output() -> None:
    assert injectors_from_sp(1_944_000) == pytest.approx(3.888)


def test_injectors_from_sp_rejects_zero_size() -> None:
    with pytest.raises(ValueError):
        injectors_from_sp(1_000_000, sp_per_injector=0)
