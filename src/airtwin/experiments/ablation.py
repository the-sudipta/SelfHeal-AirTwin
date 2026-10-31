"""Ablation variants and sensitivity settings as transformations of the configuration.

Each variant removes exactly one part of the twin, so its effect can be measured against
the full system on the same injected drifts:

* ``no_neighbours`` — expected values without the other sites;
* ``no_weather`` — expected values without local weather;
* ``ewma_only`` / ``cusum_only`` — one change detector instead of both;
* ``no_self_healing`` — drift is detected but raw values are published;
* ``no_trust_substitution`` — a faulty sensor keeps feeding its raw reading to neighbours.
"""

from __future__ import annotations

from dataclasses import replace

from airtwin.config import TargetSpec, TwinConfig

FULL = "full"
VARIANTS = (
    FULL,
    "no_neighbours",
    "no_weather",
    "ewma_only",
    "cusum_only",
    "no_self_healing",
    "no_trust_substitution",
)


def apply_variant(
    twin: TwinConfig, target: TargetSpec, variant: str
) -> tuple[TwinConfig, TargetSpec]:
    """Return the twin and target settings with one part removed (or unchanged for ``full``)."""
    if variant == FULL:
        return twin, target
    if variant == "no_neighbours":
        return twin, replace(target, use_neighbours=False)
    if variant == "no_weather":
        return twin, replace(target, use_weather=False)
    if variant == "ewma_only":
        return replace(twin, drift=replace(twin.drift, method="ewma")), target
    if variant == "cusum_only":
        return replace(twin, drift=replace(twin.drift, method="cusum")), target
    if variant == "no_self_healing":
        return replace(twin, heal=replace(twin.heal, enabled=False)), target
    if variant == "no_trust_substitution":
        return replace(twin, trust_substitution=False), target
    raise ValueError(f"unknown ablation variant {variant!r}")


def apply_sensitivity(
    twin: TwinConfig, threshold_scale: float, ewma_lambda: float | None
) -> TwinConfig:
    """Scale both alarm thresholds (EWMA limit and CUSUM h) and optionally set lambda."""
    drift = replace(
        twin.drift,
        ewma_limit=twin.drift.ewma_limit * threshold_scale,
        cusum_h=twin.drift.cusum_h * threshold_scale,
        ewma_lambda=twin.drift.ewma_lambda if ewma_lambda is None else ewma_lambda,
    )
    return replace(twin, drift=drift)


def model_inputs(target: TargetSpec) -> tuple[bool, bool, bool, bool]:
    """The switches that change the expected-value models (variants sharing them share models)."""
    return target.use_neighbours, target.use_weather, target.use_reference, target.use_time
