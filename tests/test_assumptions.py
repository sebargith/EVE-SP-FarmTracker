import pytest

from src.calculations.assumptions import (
    apply_scenario_preset,
    load_assumptions,
    with_market_overrides,
)
from src.calculations.scenarios import generate_scenario_matrix


def test_market_overrides_update_embedded_market_sources() -> None:
    assumptions = load_assumptions()
    updated = with_market_overrides(
        assumptions,
        skill_extractor_market_buy_price_isk=400_000_000,
        mct_market_buy_price_isk=2_000_000_000,
    )

    market_extractor = next(source for source in updated.extractor_sources if source.key == "market")
    market_mct = next(
        source for source in updated.regular_mct_sources if source.key == "market_certificate"
    )

    assert market_extractor.unit_isk == 400_000_000
    assert market_mct.unit_isk == 2_000_000_000


def test_market_overrides_affect_generated_scenarios() -> None:
    assumptions = load_assumptions()
    updated = with_market_overrides(
        assumptions,
        large_skill_injector_sell_price_isk=900_000_000,
        skill_extractor_market_buy_price_isk=400_000_000,
    )

    original = generate_scenario_matrix(assumptions).set_index("ID")
    changed = generate_scenario_matrix(updated).set_index("ID")

    assert changed.loc[9, "LSI Net Revenue"] > original.loc[9, "LSI Net Revenue"]
    assert changed.loc[9, "Extractor Cost ISK"] < original.loc[9, "Extractor Cost ISK"]


def test_scenario_presets_load_and_apply() -> None:
    assumptions = load_assumptions()
    updated = apply_scenario_preset(assumptions, "high_discount")

    assert len(assumptions.scenario_presets) >= 4
    assert updated.market.plex_cost_basis_isk == 4_400_000
    assert updated.market.large_skill_injector_sell_price_isk == 900_000_000


def test_unknown_scenario_preset_raises_key_error() -> None:
    with pytest.raises(KeyError):
        apply_scenario_preset(load_assumptions(), "missing")
