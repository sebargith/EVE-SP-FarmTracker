"""Typed assumptions loaded from the editable YAML file."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import yaml


DEFAULT_ASSUMPTIONS_PATH = Path(__file__).resolve().parents[2] / "data" / "assumptions.yaml"


@dataclass(frozen=True)
class MarketAssumptions:
    plex_buy_cost_isk: float
    plex_sell_value_isk: float
    plex_cost_basis_isk: float
    large_skill_injector_sell_price_isk: float
    skill_extractor_market_buy_price_isk: float
    mct_market_buy_price_isk: float
    lsi_market_fee_tax_rate: float

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "MarketAssumptions":
        return cls(
            plex_buy_cost_isk=float(values["plex_buy_cost_isk"]),
            plex_sell_value_isk=float(values["plex_sell_value_isk"]),
            plex_cost_basis_isk=float(values["plex_cost_basis_isk"]),
            large_skill_injector_sell_price_isk=float(
                values["large_skill_injector_sell_price_isk"]
            ),
            skill_extractor_market_buy_price_isk=float(
                values["skill_extractor_market_buy_price_isk"]
            ),
            mct_market_buy_price_isk=float(values["mct_market_buy_price_isk"]),
            lsi_market_fee_tax_rate=float(values["lsi_market_fee_tax_rate"]),
        )


@dataclass(frozen=True)
class TrainingAssumptions:
    optimized_sp_per_minute: float
    optimized_sp_per_month_per_queue: float
    sp_per_large_skill_injector: float
    minimum_sp_before_extraction: float
    extraction_floor_sp: float
    one_month_omega_bonus_sp: float

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "TrainingAssumptions":
        return cls(
            optimized_sp_per_minute=float(values["optimized_sp_per_minute"]),
            optimized_sp_per_month_per_queue=float(
                values["optimized_sp_per_month_per_queue"]
            ),
            sp_per_large_skill_injector=float(values["sp_per_large_skill_injector"]),
            minimum_sp_before_extraction=float(values["minimum_sp_before_extraction"]),
            extraction_floor_sp=float(values["extraction_floor_sp"]),
            one_month_omega_bonus_sp=float(values["one_month_omega_bonus_sp"]),
        )


@dataclass(frozen=True)
class TrainingPlan:
    key: str
    scenario_type: str
    name: str
    months: int
    omega_plex_total: float = 0.0
    bundle_plex_total: float = 0.0
    bonus_sp: float = 0.0

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "TrainingPlan":
        return cls(
            key=str(values["key"]),
            scenario_type=str(values["scenario_type"]),
            name=str(values["name"]),
            months=int(values["months"]),
            omega_plex_total=float(values.get("omega_plex_total", 0)),
            bundle_plex_total=float(values.get("bundle_plex_total", 0)),
            bonus_sp=float(values.get("bonus_sp", 0)),
        )


@dataclass(frozen=True)
class MctSource:
    key: str
    name: str
    unit_plex: float = 0.0
    unit_isk: float = 0.0

    @classmethod
    def from_mapping(cls, key: str, values: Mapping[str, Any]) -> "MctSource":
        return cls(
            key=key,
            name=str(values["name"]),
            unit_plex=float(values.get("unit_plex", 0)),
            unit_isk=float(values.get("unit_isk", 0)),
        )


@dataclass(frozen=True)
class ExtractorSource:
    key: str
    name: str
    unit_plex: float = 0.0
    unit_isk: float = 0.0

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "ExtractorSource":
        return cls(
            key=str(values["key"]),
            name=str(values["name"]),
            unit_plex=float(values.get("unit_plex", 0)),
            unit_isk=float(values.get("unit_isk", 0)),
        )


@dataclass(frozen=True)
class ScenarioPreset:
    key: str
    name: str
    description: str
    plex_cost_basis_isk: float
    large_skill_injector_sell_price_isk: float
    skill_extractor_market_buy_price_isk: float
    mct_market_buy_price_isk: float
    lsi_market_fee_tax_rate: float

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "ScenarioPreset":
        return cls(
            key=str(values["key"]),
            name=str(values["name"]),
            description=str(values.get("description", "")),
            plex_cost_basis_isk=float(values["plex_cost_basis_isk"]),
            large_skill_injector_sell_price_isk=float(
                values["large_skill_injector_sell_price_isk"]
            ),
            skill_extractor_market_buy_price_isk=float(
                values["skill_extractor_market_buy_price_isk"]
            ),
            mct_market_buy_price_isk=float(values["mct_market_buy_price_isk"]),
            lsi_market_fee_tax_rate=float(values["lsi_market_fee_tax_rate"]),
        )


@dataclass(frozen=True)
class FarmAssumptions:
    market: MarketAssumptions
    training: TrainingAssumptions
    omega_plans: tuple[TrainingPlan, ...]
    omega_mct_bundle_plans: tuple[TrainingPlan, ...]
    no_mct_source: MctSource
    regular_mct_sources: tuple[MctSource, ...]
    included_bundle_mct_source: MctSource
    extractor_sources: tuple[ExtractorSource, ...]
    scenario_presets: tuple[ScenarioPreset, ...]
    esi: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "FarmAssumptions":
        mct_sources = values["mct_sources"]
        return cls(
            market=MarketAssumptions.from_mapping(values["market"]),
            training=TrainingAssumptions.from_mapping(values["training"]),
            omega_plans=tuple(
                TrainingPlan.from_mapping(plan) for plan in values["omega_plans"]
            ),
            omega_mct_bundle_plans=tuple(
                TrainingPlan.from_mapping(plan)
                for plan in values["omega_mct_bundle_plans"]
            ),
            no_mct_source=MctSource.from_mapping("no_mct", mct_sources["no_mct"]),
            regular_mct_sources=tuple(
                MctSource.from_mapping(str(source["key"]), source)
                for source in mct_sources["regular"]
            ),
            included_bundle_mct_source=MctSource.from_mapping(
                "included_bundle", mct_sources["included_bundle"]
            ),
            extractor_sources=tuple(
                ExtractorSource.from_mapping(source)
                for source in values["extractor_sources"]
            ),
            scenario_presets=tuple(
                ScenarioPreset.from_mapping(preset)
                for preset in values.get("scenario_presets", ())
            ),
            esi=dict(values.get("esi", {})),
        )


def load_assumptions(path: str | Path = DEFAULT_ASSUMPTIONS_PATH) -> FarmAssumptions:
    """Load editable YAML assumptions into typed objects."""

    with Path(path).open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    return FarmAssumptions.from_mapping(raw)


def coerce_assumptions(
    assumptions: FarmAssumptions | Mapping[str, Any] | None,
) -> FarmAssumptions:
    """Accept typed assumptions, raw YAML mappings, or the default YAML file."""

    if assumptions is None:
        return load_assumptions()
    if isinstance(assumptions, FarmAssumptions):
        return assumptions
    return FarmAssumptions.from_mapping(assumptions)


def with_market_overrides(
    assumptions: FarmAssumptions,
    *,
    plex_cost_basis_isk: float | None = None,
    large_skill_injector_sell_price_isk: float | None = None,
    skill_extractor_market_buy_price_isk: float | None = None,
    mct_market_buy_price_isk: float | None = None,
    lsi_market_fee_tax_rate: float | None = None,
) -> FarmAssumptions:
    """Return assumptions with UI-provided market values applied consistently."""

    market_updates: dict[str, float] = {}
    if plex_cost_basis_isk is not None:
        market_updates["plex_cost_basis_isk"] = float(plex_cost_basis_isk)
    if large_skill_injector_sell_price_isk is not None:
        market_updates["large_skill_injector_sell_price_isk"] = float(
            large_skill_injector_sell_price_isk
        )
    if skill_extractor_market_buy_price_isk is not None:
        market_updates["skill_extractor_market_buy_price_isk"] = float(
            skill_extractor_market_buy_price_isk
        )
    if mct_market_buy_price_isk is not None:
        market_updates["mct_market_buy_price_isk"] = float(mct_market_buy_price_isk)
    if lsi_market_fee_tax_rate is not None:
        market_updates["lsi_market_fee_tax_rate"] = float(lsi_market_fee_tax_rate)

    market = replace(assumptions.market, **market_updates)
    regular_mct_sources = tuple(
        replace(source, unit_isk=market.mct_market_buy_price_isk)
        if source.key == "market_certificate"
        else source
        for source in assumptions.regular_mct_sources
    )
    extractor_sources = tuple(
        replace(source, unit_isk=market.skill_extractor_market_buy_price_isk)
        if source.key == "market"
        else source
        for source in assumptions.extractor_sources
    )

    return replace(
        assumptions,
        market=market,
        regular_mct_sources=regular_mct_sources,
        extractor_sources=extractor_sources,
    )


def apply_scenario_preset(
    assumptions: FarmAssumptions,
    preset_key: str,
) -> FarmAssumptions:
    """Return assumptions with a named scenario preset applied."""

    preset = next(
        (candidate for candidate in assumptions.scenario_presets if candidate.key == preset_key),
        None,
    )
    if preset is None:
        raise KeyError(f"Unknown scenario preset: {preset_key}")

    return with_market_overrides(
        assumptions,
        plex_cost_basis_isk=preset.plex_cost_basis_isk,
        large_skill_injector_sell_price_isk=preset.large_skill_injector_sell_price_isk,
        skill_extractor_market_buy_price_isk=preset.skill_extractor_market_buy_price_isk,
        mct_market_buy_price_isk=preset.mct_market_buy_price_isk,
        lsi_market_fee_tax_rate=preset.lsi_market_fee_tax_rate,
    )
