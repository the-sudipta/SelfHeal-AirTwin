"""The virtual entity: for every sensor, the value it *should* read this hour.

Each sensor gets its own LightGBM regressor. Its inputs are the same variable at the
neighbouring sites, the weather at its own site, the co-located reference analyzer when
one exists, and the hour of day. The models learn from an initial calibration window and
are then applied hour by hour; a sensor's own reading is never one of its inputs, so a
drifting sensor cannot pull its expected value along with it.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np

from airtwin.config import ModelParams, TargetSpec
from airtwin.stream.interface import Tick
from airtwin.twin.state import SensorKey

HOUR_SIN = "hour_sin"
HOUR_COS = "hour_cos"
HOURS_PER_DAY = 24

Row = Mapping[str, float]


def flatten(tick: Tick) -> dict[str, float]:
    """Turn one tick into a flat row keyed ``site:variable`` plus the hour-of-day features."""
    row = {str(SensorKey(r.site, var)): v for r in tick.readings for var, v in r.values.items()}
    angle = 2 * math.pi * tick.timestamp.hour / HOURS_PER_DAY
    row[HOUR_SIN] = math.sin(angle)
    row[HOUR_COS] = math.cos(angle)
    return row


@dataclass(frozen=True)
class FeatureSpec:
    """The target sensor of one model and the ordered names of its input columns."""

    target: SensorKey
    features: tuple[str, ...]

    def __post_init__(self) -> None:
        """A model must have inputs and must never see its own target."""
        if not self.features:
            raise ValueError(f"{self.target}: no input features")
        if str(self.target) in self.features:
            raise ValueError(f"{self.target}: target cannot be one of its own features")


def build_specs(sites: Sequence[str], target: TargetSpec) -> list[FeatureSpec]:
    """Create one feature spec per site and target variable, following the ``use_*`` switches."""
    specs = []
    for site in sorted(sites):
        for variable in target.variables:
            features: list[str] = []
            if target.use_neighbours:
                features += [str(SensorKey(s, variable)) for s in sorted(sites) if s != site]
            if target.use_weather:
                features += [str(SensorKey(site, w)) for w in target.weather]
            if target.use_reference:
                features += [str(SensorKey(site, r)) for r in target.reference]
            if target.use_time:
                features += [HOUR_SIN, HOUR_COS]
            specs.append(FeatureSpec(SensorKey(site, variable), tuple(features)))
    return specs


def _lgb_params(params: ModelParams) -> dict[str, Any]:
    """LightGBM settings that make training deterministic and single-threaded."""
    return {
        "objective": "regression",
        "learning_rate": params.learning_rate,
        "num_leaves": params.num_leaves,
        "min_data_in_leaf": params.min_data_in_leaf,
        "seed": params.seed,
        "deterministic": True,
        "force_col_wise": True,
        "num_threads": 1,
        "verbosity": -1,
    }


class ExpectedModel:
    """One sensor's expected-value regressor."""

    def __init__(self, spec: FeatureSpec, params: ModelParams) -> None:
        """Create an untrained model."""
        self.spec = spec
        self._params = params
        self._booster: lgb.Booster | None = None
        self.training_rows = 0

    @property
    def trained(self) -> bool:
        """True once :meth:`fit` found enough usable rows."""
        return self._booster is not None

    def _matrix(self, rows: Sequence[Row]) -> np.ndarray:
        """Stack the feature values of several rows; missing columns become NaN."""
        return np.array(
            [[row.get(f, math.nan) for f in self.spec.features] for row in rows], dtype="float64"
        )

    def fit(self, rows: Sequence[Row], min_rows: int) -> bool:
        """Train on the rows whose target is present.

        Returns:
            True if the model was trained, False if fewer than ``min_rows`` rows were usable.
        """
        target = str(self.spec.target)
        usable = [r for r in rows if not math.isnan(r.get(target, math.nan))]
        self.training_rows = len(usable)
        if len(usable) < min_rows:
            self._booster = None
            return False
        data = lgb.Dataset(
            self._matrix(usable),
            label=np.array([r[target] for r in usable], dtype="float64"),
            feature_name=[f.replace(":", "__") for f in self.spec.features],
            free_raw_data=True,
        )
        self._booster = lgb.train(
            _lgb_params(self._params), data, num_boost_round=self._params.n_estimators
        )
        return True

    def predict_many(self, rows: Sequence[Row]) -> np.ndarray:
        """Expected values for several rows; all NaN if the model is not trained."""
        if self._booster is None or not rows:
            return np.full(len(rows), math.nan)
        return np.asarray(self._booster.predict(self._matrix(rows)), dtype="float64")

    def predict(self, row: Row) -> float:
        """Expected value for one row."""
        return float(self.predict_many([row])[0])


class ExpectedValueBank:
    """All sensors' models: collects the calibration window, trains once, then predicts."""

    def __init__(
        self,
        specs: Sequence[FeatureSpec],
        params: ModelParams,
        calibration_hours: int,
        min_training_rows: int,
    ) -> None:
        """Create untrained models for every spec."""
        self.models = {s.target: ExpectedModel(s, params) for s in specs}
        self._calibration_hours = calibration_hours
        self._min_rows = min_training_rows
        self._buffer: list[Row] = []
        self.calibrated = False

    def observe(self, row: Row) -> dict[SensorKey, float]:
        """Feed one hour; return each sensor's expected value (NaN during calibration).

        The hour that completes the calibration window is used for training and still
        returns NaN; predictions start with the following hour.
        """
        if self.calibrated:
            return {key: model.predict(row) for key, model in self.models.items()}
        self._buffer.append(row)
        if len(self._buffer) >= self._calibration_hours:
            for model in self.models.values():
                model.fit(self._buffer, self._min_rows)
            self._buffer = []
            self.calibrated = True
        return {key: math.nan for key in self.models}

    def predict(self, row: Row, keys: Iterable[SensorKey]) -> dict[SensorKey, float]:
        """Expected values of selected sensors for one row (NaN before calibration)."""
        if not self.calibrated:
            return {key: math.nan for key in keys}
        return {key: self.models[key].predict(row) for key in keys}

    def trained_keys(self) -> list[SensorKey]:
        """Sensors whose model is trained, in key order."""
        return sorted(k for k, m in self.models.items() if m.trained)
