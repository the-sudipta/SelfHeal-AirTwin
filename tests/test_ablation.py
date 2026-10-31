from pathlib import Path

import pytest

from airtwin.config import load_config
from airtwin.experiments.ablation import (
    FULL,
    VARIANTS,
    apply_sensitivity,
    apply_variant,
    model_inputs,
)

CFG = load_config(Path(__file__).resolve().parents[1] / "configs" / "default.yaml")
TWIN = CFG.twin
TARGET = CFG.twin.target("beijing_multisite")


def test_each_variant_changes_exactly_one_thing() -> None:
    assert apply_variant(TWIN, TARGET, FULL) == (TWIN, TARGET)
    _, t = apply_variant(TWIN, TARGET, "no_neighbours")
    assert not t.use_neighbours and t.use_weather
    _, t = apply_variant(TWIN, TARGET, "no_weather")
    assert t.use_neighbours and not t.use_weather
    assert apply_variant(TWIN, TARGET, "ewma_only")[0].drift.method == "ewma"
    assert apply_variant(TWIN, TARGET, "cusum_only")[0].drift.method == "cusum"
    assert apply_variant(TWIN, TARGET, "no_self_healing")[0].heal.enabled is False
    assert apply_variant(TWIN, TARGET, "no_trust_substitution")[0].trust_substitution is False
    assert len(VARIANTS) == 7
    with pytest.raises(ValueError, match="unknown ablation variant"):
        apply_variant(TWIN, TARGET, "no_brain")


def test_model_inputs_group_variants() -> None:
    shared = {model_inputs(apply_variant(TWIN, TARGET, v)[1]) for v in VARIANTS}
    assert len(shared) == 3  # full-like, no_neighbours, no_weather


def test_sensitivity_scales_thresholds_and_sets_lambda() -> None:
    twin = apply_sensitivity(TWIN, 2.0, 0.1)
    assert twin.drift.ewma_limit == 2 * TWIN.drift.ewma_limit
    assert twin.drift.cusum_h == 2 * TWIN.drift.cusum_h
    assert twin.drift.ewma_lambda == 0.1
    assert apply_sensitivity(TWIN, 1.0, None).drift == TWIN.drift
