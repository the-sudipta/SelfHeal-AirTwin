"""Statistics over repeated runs: mean with a 95% confidence interval and paired tests.

* The confidence interval uses Student's t distribution over the runs.
* The paired comparison is the Wilcoxon signed-rank test (two-sided, zero differences
  dropped), with the matched-pairs rank-biserial correlation as effect size: +1 means the
  first method is better (lower) in every pair, -1 worse in every pair.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy import stats

CONFIDENCE = 0.95
Values = Sequence[float] | np.ndarray


@dataclass(frozen=True)
class MeanCI:
    """Mean and its confidence interval."""

    mean: float
    low: float
    high: float
    n: int


def mean_ci(values: Values, confidence: float = CONFIDENCE) -> MeanCI:
    """Mean of the finite values with a t-based confidence interval."""
    data = np.asarray([v for v in values if math.isfinite(v)], dtype="float64")
    n = len(data)
    if n == 0:
        return MeanCI(math.nan, math.nan, math.nan, 0)
    mean = float(np.mean(data))
    if n == 1:
        return MeanCI(mean, math.nan, math.nan, 1)
    half = float(stats.t.ppf((1 + confidence) / 2, n - 1) * np.std(data, ddof=1) / math.sqrt(n))
    return MeanCI(mean, mean - half, mean + half, n)


@dataclass(frozen=True)
class PairedTest:
    """Wilcoxon signed-rank test of ``a`` against ``b`` (lower is better)."""

    n: int
    statistic: float
    p_value: float
    effect_size: float  # rank-biserial correlation, positive when a < b
    median_difference: float  # median of a - b


def wilcoxon_paired(a: Values, b: Values) -> PairedTest:
    """Paired comparison over the pairs where both values are finite."""
    x = np.asarray(a, dtype="float64")
    y = np.asarray(b, dtype="float64")
    ok = np.isfinite(x) & np.isfinite(y)
    diff = x[ok] - y[ok]
    nonzero = diff[diff != 0]
    if len(nonzero) == 0:
        return PairedTest(int(ok.sum()), math.nan, 1.0, 0.0, 0.0)
    result = stats.wilcoxon(x[ok], y[ok], zero_method="wilcox", alternative="two-sided")
    ranks = stats.rankdata(np.abs(nonzero))
    better = float(ranks[nonzero < 0].sum())  # pairs where a is lower
    worse = float(ranks[nonzero > 0].sum())
    effect = (better - worse) / (better + worse)
    return PairedTest(
        int(ok.sum()),
        float(result.statistic),
        float(result.pvalue),
        effect,
        float(np.median(diff)),
    )
