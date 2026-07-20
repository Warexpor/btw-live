"""Display envelope + frame energy for viz meters."""
from __future__ import annotations

import numpy as np

from btw.audio_io import (
    MIC_LIVE_EDGE_SAMPLES,
    SAMPLE_RATE,
    _Envelope,
    _FloatRing,
    _declick_join,
    _fade_from_hold,
    _frame_level,
    _soften_intra_clicks,
)


def test_envelope_attack_and_release():
    env = _Envelope(release=0.9)
    assert env.update(0.0) == 0.0
    assert env.update(0.8) == 0.8  # instant attack
    mid = env.update(0.0)
    assert 0.0 < mid < 0.8
    # more release steps
    for _ in range(40):
        env.update(0.0)
    assert env.value < 0.05


def test_frame_level_tracks_speech_not_silence():
    silence = np.zeros(960, dtype=np.float32)
    assert _frame_level(silence) == 0.0

    speech = np.sin(np.linspace(0, 40 * np.pi, 960)).astype(np.float32) * 0.2
    lvl = _frame_level(speech)
    assert 0.05 < lvl < 1.0

    loud = speech * 4.0
    assert _frame_level(loud) >= lvl


def test_drop_to_keeps_live_edge():
    r = _FloatRing(SAMPLE_RATE * 3)
    r.write(np.ones(SAMPLE_RATE, dtype=np.float32))
    assert r.size == SAMPLE_RATE
    dropped = r.drop_to(MIC_LIVE_EDGE_SAMPLES)
    assert dropped == SAMPLE_RATE - MIC_LIVE_EDGE_SAMPLES
    assert r.size == MIC_LIVE_EDGE_SAMPLES
    got = r.read(MIC_LIVE_EDGE_SAMPLES)
    assert float(got.mean()) == 1.0


def test_drop_to_noop_when_small():
    r = _FloatRing(1000)
    r.write(np.ones(100, dtype=np.float32))
    assert r.drop_to(200) == 0
    assert r.size == 100


def test_declick_join_softens_hard_edge():
    # large discontinuity (inject edge); mild speech jumps must not ramp
    mono = np.full(960, 0.5, dtype=np.float32)
    mono[0] = 0.8
    out = _declick_join(0.0, mono, n=48)
    assert abs(float(out[0])) < 0.15  # starts near hold
    assert float(out[47]) > 0.3
    speech = np.linspace(-0.2, 0.2, 960, dtype=np.float32)
    assert np.allclose(_declick_join(0.0, speech), speech)


def test_soften_intra_clicks_kills_spike():
    x = np.zeros(64, dtype=np.float32)
    x[19] = 0.05
    x[20] = 0.99  # digital spike
    x[21] = 0.05
    out = _soften_intra_clicks(x, jump=0.85)
    assert abs(float(out[20])) < 0.5
    # normal speech untouched
    s = (np.sin(np.linspace(0, 20 * np.pi, 960)) * 0.3).astype(np.float32)
    assert np.allclose(_soften_intra_clicks(s), s)


def test_fade_from_hold_decays():
    y = _fade_from_hold(0.5, 100)
    assert y.size == 100
    assert float(y[0]) == 0.5
    assert abs(float(y[-1])) < abs(float(y[0]))
