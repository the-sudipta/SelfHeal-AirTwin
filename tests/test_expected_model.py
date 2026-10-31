import math
from datetime import datetime, timedelta

import numpy as np
import pytest

from airtwin.config import ModelParams, TargetSpec
from airtwin.stream.interface import Reading, Tick
from airtwin.twin.expected_model import (
    HOUR_COS,
    HOUR_SIN,
    ExpectedModel,
    ExpectedValueBank,
    FeatureSpec,
    build_specs,
    flatten,
)
from airtwin.twin.state import SensorKey

PARAMS = ModelParams(n_estimators=60, learning_rate=0.1, num_leaves=8, min_data_in_leaf=5, seed=7)
T0 = datetime(2013, 3, 1)


def target_spec(**overrides: object) -> TargetSpec:
    base = {
        "variables": ("pm25",),
        "weather": ("temperature",),
        "reference": (),
        "use_neighbours": True,
        "use_weather": True,
        "use_reference": True,
        "use_time": True,
    }
    return TargetSpec(**{**base, **overrides})  # type: ignore[arg-type]


def synthetic_rows(n: int, seed: int = 0) -> list[dict[str, float]]:
    """Site C reads 2 x the mean of A and B plus a temperature effect."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        a, b = rng.uniform(10, 100, size=2)
        temp = rng.uniform(-5, 30)
        rows.append(
            {
                "A:pm25": a,
                "B:pm25": b,
                "C:pm25": (a + b) + 0.5 * temp,
                "C:temperature": temp,
                HOUR_SIN: math.sin(i),
                HOUR_COS: math.cos(i),
            }
        )
    return rows


def test_flatten_builds_site_variable_row_with_hour() -> None:
    tick = Tick(T0 + timedelta(hours=6), (Reading("A", {"pm25": 3.0, "no2": math.nan}),))
    row = flatten(tick)
    assert row["A:pm25"] == 3.0
    assert math.isnan(row["A:no2"])
    assert row[HOUR_SIN] == pytest.approx(1.0)
    assert row[HOUR_COS] == pytest.approx(0.0, abs=1e-12)


def test_build_specs_follows_switches_and_never_uses_target() -> None:
    specs = build_specs(["B", "A"], target_spec(reference=("co_ref",)))
    assert [str(s.target) for s in specs] == ["A:pm25", "B:pm25"]
    assert specs[0].features == ("B:pm25", "A:temperature", "A:co_ref", HOUR_SIN, HOUR_COS)
    only_weather = build_specs(
        ["A", "B"], target_spec(use_neighbours=False, use_reference=False, use_time=False)
    )
    assert only_weather[0].features == ("A:temperature",)
    with pytest.raises(ValueError, match="no input features"):
        build_specs(["A"], target_spec(use_weather=False, use_time=False))
    with pytest.raises(ValueError, match="own features"):
        FeatureSpec(SensorKey("A", "pm25"), ("A:pm25",))


def test_model_learns_relationship_and_handles_missing_inputs() -> None:
    spec = FeatureSpec(SensorKey("C", "pm25"), ("A:pm25", "B:pm25", "C:temperature"))
    model = ExpectedModel(spec, PARAMS)
    assert math.isnan(model.predict(synthetic_rows(1)[0]))
    assert model.fit(synthetic_rows(600), min_rows=50)
    test = synthetic_rows(200, seed=1)
    pred = model.predict_many(test)
    truth = np.array([r["C:pm25"] for r in test])
    spread = truth.std()
    assert np.sqrt(np.mean((pred - truth) ** 2)) < 0.25 * spread
    partial = dict(test[0])
    del partial["B:pm25"]
    assert math.isfinite(model.predict(partial))


def test_training_is_deterministic() -> None:
    spec = FeatureSpec(SensorKey("C", "pm25"), ("A:pm25", "B:pm25", "C:temperature"))
    rows = synthetic_rows(300)
    first, second = ExpectedModel(spec, PARAMS), ExpectedModel(spec, PARAMS)
    first.fit(rows, 50)
    second.fit(rows, 50)
    test = synthetic_rows(20, seed=3)
    assert np.array_equal(first.predict_many(test), second.predict_many(test))


def test_too_few_target_values_leaves_model_untrained() -> None:
    spec = FeatureSpec(SensorKey("C", "pm25"), ("A:pm25",))
    rows = [{**r, "C:pm25": math.nan} for r in synthetic_rows(100)]
    model = ExpectedModel(spec, PARAMS)
    assert not model.fit(rows, min_rows=10)
    assert model.training_rows == 0
    assert np.isnan(model.predict_many(rows[:3])).all()
    assert model.predict_many([]).shape == (0,)


def test_bank_calibrates_then_predicts() -> None:
    specs = [
        FeatureSpec(SensorKey("C", "pm25"), ("A:pm25", "B:pm25", "C:temperature")),
        FeatureSpec(SensorKey("Z", "pm25"), ("A:pm25",)),
    ]
    bank = ExpectedValueBank(specs, PARAMS, calibration_hours=300, min_training_rows=50)
    rows = synthetic_rows(301)
    outputs = [bank.observe(r) for r in rows]
    assert all(math.isnan(v) for out in outputs[:300] for v in out.values())
    assert bank.calibrated
    assert bank.trained_keys() == [SensorKey("C", "pm25")]
    last = outputs[300]
    assert math.isfinite(last[SensorKey("C", "pm25")])
    assert math.isnan(last[SensorKey("Z", "pm25")])
