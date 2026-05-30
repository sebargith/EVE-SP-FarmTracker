from src.calculations.scenarios import (
    filter_profitable,
    generate_scenario_matrix,
    rank_scenarios,
)


def test_generate_scenario_matrix_shape_and_order() -> None:
    df = generate_scenario_matrix()

    assert len(df) == 927
    assert df.iloc[0]["ID"] == 1
    assert df.iloc[0]["Training / Omega Offer"] == "1M Omega + Bonus Items"
    assert df.iloc[0]["Queues"] == 1
    assert df.iloc[0]["MCT Source"] == "No MCT"
    assert df.iloc[-1]["ID"] == 927
    assert df.iloc[-1]["Training / Omega Offer"] == "12M Omega + 24M MCT 50% bundle"
    assert df.iloc[-1]["Extractor Source"] == "Market Skill Extractor"


def test_known_first_scenario_outputs() -> None:
    row = generate_scenario_matrix().iloc[0]

    assert row["Training Cost ISK"] == 2_405_000_000
    assert row["Total SP"] == 2_044_000
    assert row["Injectors Produced"] == 4.088
    assert row["Extractor Cost ISK"] == 2_752_859_200
    assert row["LSI Net Revenue"] == 2_923_962_440
    assert row["Profit ISK"] == -2_233_896_760
    assert row["Status"] == "LOSS"


def test_rank_scenarios_sorts_by_profit_descending() -> None:
    ranked = rank_scenarios(generate_scenario_matrix())

    assert ranked["Profit ISK"].is_monotonic_decreasing


def test_filter_profitable_returns_only_positive_profit() -> None:
    profitable = filter_profitable(generate_scenario_matrix())

    assert (profitable["Profit ISK"] > 0).all()
