import math

import numpy as np
import pytest
from scipy import stats

from airtwin.experiments.stats import mean_ci, wilcoxon_paired


def test_mean_ci_matches_t_interval() -> None:
    data = [1.0, 2.0, 3.0, 4.0, 5.0, math.nan]
    ci = mean_ci(data)
    half = stats.t.ppf(0.975, 4) * np.std([1, 2, 3, 4, 5], ddof=1) / math.sqrt(5)
    assert ci.n == 5 and ci.mean == 3.0
    assert ci.low == pytest.approx(3 - half) and ci.high == pytest.approx(3 + half)
    assert mean_ci([]).n == 0 and math.isnan(mean_ci([]).mean)
    single = mean_ci([2.0])
    assert single.mean == 2.0 and math.isnan(single.low)


def test_wilcoxon_effect_size_direction() -> None:
    rng = np.random.default_rng(0)
    b = rng.uniform(5, 10, 30)
    a = b - rng.uniform(0.5, 1.5, 30)  # a always lower
    test = wilcoxon_paired(a, b)
    assert test.n == 30
    assert test.p_value < 0.001
    assert test.effect_size == pytest.approx(1.0)
    assert test.median_difference < 0
    assert wilcoxon_paired(b, a).effect_size == pytest.approx(-1.0)


def test_wilcoxon_identical_and_missing() -> None:
    same = wilcoxon_paired([1.0, 2.0, math.nan], [1.0, 2.0, 3.0])
    assert same.n == 2 and same.p_value == 1.0 and same.effect_size == 0.0
