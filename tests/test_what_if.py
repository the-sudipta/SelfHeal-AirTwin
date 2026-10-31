from datetime import datetime, timedelta

import pytest

from airtwin.twin.state import SensorKey
from airtwin.twin.what_if import project

KEY = SensorKey("A", "pm25")
NOW = datetime(2015, 6, 15)


def test_linear_growth_is_extrapolated() -> None:
    history = [(NOW - timedelta(days=d), 0.20 - 0.01 * d) for d in (10, 7, 4, 1, 0)]
    result = project(KEY, history, NOW, [7, 14, 30], history_hours=336)
    assert result.rate_per_day == pytest.approx(0.01)
    assert result.current_relative_error == pytest.approx(0.20)
    assert [p.horizon_days for p in result.projections] == [7, 14, 30]
    assert [p.relative_error for p in result.projections] == pytest.approx([0.27, 0.34, 0.50])
    assert result.points_used == 5
    assert result.basis.startswith("linear trend of 5 corrections over 10.0 days")


def test_old_points_outside_history_are_ignored() -> None:
    history = [(NOW - timedelta(days=30), 5.0), (NOW - timedelta(days=2), 0.1), (NOW, 0.1)]
    result = project(KEY, history, NOW, [7], history_hours=24 * 14)
    assert result.points_used == 2
    assert result.rate_per_day == pytest.approx(0.0)
    assert result.projections[0].relative_error == pytest.approx(0.1)


def test_single_point_holds_error_constant() -> None:
    result = project(KEY, [(NOW, -0.15)], NOW, [7, 30], history_hours=336)
    assert result.rate_per_day == 0.0
    assert [p.relative_error for p in result.projections] == [-0.15, -0.15]
    assert "single correction" in result.basis


def test_no_history_means_healthy() -> None:
    result = project(KEY, [], NOW, [7], history_hours=336)
    assert result.points_used == 0
    assert result.projections[0].relative_error == 0.0
    assert "healthy" in result.basis
