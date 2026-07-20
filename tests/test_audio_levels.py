"""Display envelope + frame energy for viz meters."""
from __future__ import annotations

import numpy as np

from btw.audio_io import _Envelope, _frame_level


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
