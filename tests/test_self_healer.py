import math
from dataclasses import replace

import numpy as np
import pytest

from airtwin.config import HealSettings
from airtwin.twin.self_healer import (
    SelfHealer,
    SelfHealerBank,
    fit_correction,
    relative_effect,
)
from airtwin.twin.state import IDENTITY, Correction, SensorKey

SETTINGS = HealSettings(
    fit_hours=168,
    min_pairs=48,
    gain_min_pairs=72,
    refit_hours=24,
    fit_gain=True,
    min_gain=0.25,
    max_gain=4.0,
    trim_mad=3.0,
    min_effect=0.1,
    min_improvement=0.3,
)


def pairs(n: int, gain: float, offset: float, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    expected = rng.uniform(10, 150, n)
    raw = gain * expected + offset + rng.normal(0, 2, n)
    return expected, raw


def test_fit_recovers_gain_and_offset() -> None:
    expected, raw = pairs(168, gain=1.3, offset=8.0)
    result = fit_correction(expected, raw, SETTINGS)
    assert result is not None
    assert result.correction.gain == pytest.approx(1.3, abs=0.02)
    assert result.correction.offset == pytest.approx(8.0, abs=1.5)
    corrected = result.correction.apply(raw)
    assert np.sqrt(np.mean((corrected - expected) ** 2)) < 2.0


def test_fit_ignores_outliers_and_missing_pairs() -> None:
    expected, raw = pairs(168, gain=1.0, offset=5.0)
    raw[:10] = 1000.0  # spikes
    raw[10:20] = np.nan
    result = fit_correction(expected, raw, SETTINGS)
    assert result is not None
    assert result.correction.offset == pytest.approx(5.0, abs=1.0)
    assert result.pairs < 158


def test_offset_only_mode_and_constant_expected() -> None:
    expected, raw = pairs(100, gain=1.0, offset=-4.0)
    offset_only = replace(SETTINGS, fit_gain=False)
    result = fit_correction(expected, raw, offset_only)
    assert result is not None and result.correction.gain == 1.0
    assert result.correction.offset == pytest.approx(-4.0, abs=1.0)
    flat = fit_correction(np.full(100, 50.0), np.full(100, 53.0), SETTINGS)
    assert flat is not None
    assert flat.correction == Correction(offset=3.0, gain=1.0)


def test_gain_is_clipped_to_bounds() -> None:
    expected, raw = pairs(168, gain=9.0, offset=0.0)
    result = fit_correction(expected, raw, SETTINGS)
    assert result is not None
    assert result.correction.gain == SETTINGS.max_gain


def test_too_few_pairs_gives_no_fit() -> None:
    expected, raw = pairs(10, gain=1.2, offset=0.0)
    assert fit_correction(expected, raw, SETTINGS) is None


def test_healer_lifecycle_heal_refit_clear() -> None:
    healer = SelfHealer(SETTINGS)
    assert healer.maybe_refit() is None
    expected, raw = pairs(30, gain=1.2, offset=0.0)
    for e, r in zip(expected, raw, strict=True):
        healer.observe(float(r), float(e))
    assert healer.heal() is None  # 30 < 48 pairs
    assert not healer.active
    expected, raw = pairs(168, gain=1.2, offset=0.0, seed=1)
    for e, r in zip(expected, raw, strict=True):
        healer.observe(float(r), float(e))
    first = healer.heal()
    assert first is not None and healer.active
    assert first.gain == pytest.approx(1.2, abs=0.03)
    for e in expected[:23]:
        healer.observe(1.5 * float(e), float(e))
    assert healer.maybe_refit() is None  # 23 < 24 hours
    healer.observe(1.5 * float(expected[23]), float(expected[23]))
    second = healer.maybe_refit()
    assert second is not None and second.gain > first.gain
    short = healer.heal(window=60)  # below gain_min_pairs: offset only
    assert short is not None and short.gain == 1.0
    fresh_expected, fresh_raw = pairs(80, gain=1.5, offset=0.0, seed=2)
    for e, r in zip(fresh_expected, fresh_raw, strict=True):
        healer.observe(float(r), float(e))
    windowed = healer.heal(window=80)  # only the 80 newest pairs, all at gain 1.5
    assert windowed is not None
    assert windowed.gain == pytest.approx(1.5, abs=0.03)
    healer.clear()
    assert healer.correction is IDENTITY and not healer.active


def test_bank_and_relative_effect() -> None:
    key = SensorKey("A", "pm25")
    bank = SelfHealerBank([key], SETTINGS)
    assert bank[key].correction is IDENTITY
    assert relative_effect(IDENTITY, 50.0) == 0.0
    assert relative_effect(Correction(offset=10.0, gain=1.0), 50.0) == pytest.approx(0.2)
    assert relative_effect(Correction(offset=0.0, gain=0.8), 50.0) == pytest.approx(-0.2)
    assert relative_effect(Correction(offset=1.0), math.nan) == 0.0
    assert relative_effect(Correction(offset=1.0), 0.0) == 0.0


def test_propose_reports_evidence_without_applying() -> None:
    healer = SelfHealer(SETTINGS)
    expected, raw = pairs(120, gain=1.0, offset=30.0)  # level ~80: reads ~37% high
    for e, r in zip(expected, raw, strict=True):
        healer.observe(float(r), float(e))
    proposal = healer.propose()
    assert proposal is not None
    assert proposal.relative_error > 0.25
    assert proposal.improvement > 0.8
    assert not healer.active and healer.correction is IDENTITY
    healer.accept(proposal.correction)
    assert healer.active
    healer.deactivate()
    assert not healer.active and healer.correction is IDENTITY
    assert healer.typical_level() > 0  # the pair window is kept


def test_healthy_pairs_give_a_small_unhelpful_proposal() -> None:
    healer = SelfHealer(SETTINGS)
    expected, raw = pairs(120, gain=1.0, offset=0.0)
    for e, r in zip(expected, raw, strict=True):
        healer.observe(float(r), float(e))
    proposal = healer.propose()
    assert proposal is not None
    assert abs(proposal.relative_error) < 0.05
    assert proposal.improvement < 0.3
