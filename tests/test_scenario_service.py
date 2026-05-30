from src.calculations.assumptions import load_assumptions
from src.services.scenario_service import (
    baseline_monthly_profit,
    best_scenario,
    extractor_cost_sensitivity,
    lsi_price_sensitivity,
    profitable_scenarios,
    ranked_scenarios,
    scenario_matrix_for_market,
)


def test_scenario_matrix_for_market_applies_overrides() -> None:
    assumptions = load_assumptions()

    df = scenario_matrix_for_market(
        assumptions,
        plex_cost_basis_isk=4_400_000,
        large_skill_injector_sell_price_isk=900_000_000,
        skill_extractor_market_buy_price_isk=400_000_000,
        mct_market_buy_price_isk=2_000_000_000,
        lsi_market_fee_tax_rate=0.05,
    )

    market_extractor_row = df[df["ID"] == 9].iloc[0]
    assert market_extractor_row["Extractor Unit ISK"] == 400_000_000
    assert market_extractor_row["LSI Gross Revenue"] > 0


def test_best_and_baseline_helpers() -> None:
    df = scenario_matrix_for_market(
        load_assumptions(),
        plex_cost_basis_isk=4_810_000,
        large_skill_injector_sell_price_isk=752_900_000,
        skill_extractor_market_buy_price_isk=463_500_000,
        mct_market_buy_price_isk=2_332_850_000,
        lsi_market_fee_tax_rate=0.05,
    )

    assert len(ranked_scenarios(df)) == len(df)
    assert best_scenario(df)["Profit ISK"] == ranked_scenarios(df).iloc[0]["Profit ISK"]
    assert len(profitable_scenarios(df)) == 29
    assert baseline_monthly_profit(df) == df[df["ID"] == 1].iloc[0][
        "Profit / Calendar Month ISK"
    ]


def test_sensitivity_helpers_return_expected_shapes() -> None:
    df = scenario_matrix_for_market(
        load_assumptions(),
        plex_cost_basis_isk=4_810_000,
        large_skill_injector_sell_price_isk=752_900_000,
        skill_extractor_market_buy_price_isk=463_500_000,
        mct_market_buy_price_isk=2_332_850_000,
        lsi_market_fee_tax_rate=0.05,
    )
    best = best_scenario(df)

    assert list(lsi_price_sensitivity(best).columns) == ["LSI Price", "Profit / Month"]
    assert len(lsi_price_sensitivity(best)) == 7
    assert list(extractor_cost_sensitivity(best).columns) == [
        "Extractor Cost",
        "Profit / Month",
    ]
    assert len(extractor_cost_sensitivity(best)) == 5
