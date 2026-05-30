import pytest

from src.calculations.assumptions import load_assumptions
from src.calculations.scenario_engine import evaluate_scenario
from src.domain.scenarios import ScenarioInput, ScenarioResult, TrainingPlanResult


def test_evaluate_scenario_returns_domain_result() -> None:
    result = evaluate_scenario(
        ScenarioInput(
            scenario_id=1,
            scenario_type="Base",
            training_offer="1M Omega + Bonus Items",
            omega_months=1,
            queue_count=1,
            mct_source="No MCT",
            extractor_source="NES single extractor",
            omega_plex_total=500,
            mct_unit_plex=0,
            mct_market_unit_isk=0,
            bundle_plex_total=0,
            bonus_sp=100_000,
            extractor_unit_plex=140,
            extractor_unit_isk=0,
            notes="Reference scenario.",
        ),
        load_assumptions(),
    )

    assert isinstance(result, ScenarioResult)
    assert isinstance(result.training, TrainingPlanResult)
    assert result.training.total_sp == 2_044_000
    assert result.training.injectors_produced == pytest.approx(4.088)
    assert result.extractor_cost_isk == pytest.approx(2_752_859_200)
    assert result.profit_isk == pytest.approx(-2_233_896_760)
    assert result.status == "LOSS"
