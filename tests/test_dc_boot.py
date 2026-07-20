"""Unit tests for deferred plain-text boot inject (no real WebRTC)."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btw.live_session import (  # noqa: E402
    BOOT_INJECT_WAIT_S,
    DC_LABEL,
    DC_NEGOTIATED_ID,
    LiveSession,
)
from btw.profiles import SessionProfile  # noqa: E402


class _FakeDC:
    def __init__(self, ready: str = "open"):
        self.readyState = ready
        self.label = ""
        self.id = DC_NEGOTIATED_ID
        self.sent: list[str] = []

    def send(self, data):
        if self.readyState != "open":
            raise RuntimeError("not open")
        self.sent.append(data if isinstance(data, str) else repr(data))


def _session() -> LiveSession:
    prof = SessionProfile(
        name="test",
        voice="maple",
        voice_mode="wingman",
        description="test",
        system="You advise only.",
        context_max_chars=4000,
    )
    return LiveSession(
        prof,
        instructions="You advise only.\n\n## Context\nfact-a",
        context="fact-a",
        use_mic=False,
        use_speaker=False,
    )


def test_boot_inject_sync_sends_exactly_one_plain():
    s = _session()
    dc = _FakeDC()
    n = s._boot_inject_sync(dc, tag="boot_test")
    assert n == 1
    assert len(dc.sent) == 1
    assert "BTW-VC SESSION BRIEF" in dc.sent[0]
    assert "fact-a" in dc.sent[0]
    # second call must not send again
    n2 = s._boot_inject_sync(dc, tag="boot_again")
    assert n2 == 0
    assert len(dc.sent) == 1


def test_boot_inject_skips_when_closed():
    s = _session()
    dc = _FakeDC(ready="closed")
    n = s._boot_inject_sync(dc)
    assert n == 0
    assert dc.sent == []


def test_arm_boot_sends_immediately_on_open():
    s = _session()
    dc = _FakeDC()
    s._arm_boot_inject(dc)
    assert s._boot_inject_done is True
    assert len(dc.sent) == 1
    assert s.stats.get("boot_inject_reason") == "open"
    # arm again must no-op
    s._arm_boot_inject(dc)
    assert len(dc.sent) == 1


def test_deferred_boot_on_first_inbound():
    async def _run():
        s = _session()
        s._loop = asyncio.get_running_loop()
        s._dc_first_inbound = asyncio.Event()
        s._dc_first_inbound.set()
        dc = _FakeDC()
        await s._deferred_boot_inject(dc)
        assert s._boot_inject_done is True
        assert len(dc.sent) == 1
        assert s.stats.get("boot_inject_reason") == "first_inbound"

    asyncio.run(_run())


def test_deferred_boot_once_only():
    async def _run():
        s = _session()
        s._loop = asyncio.get_running_loop()
        s._dc_first_inbound = asyncio.Event()
        s._dc_first_inbound.set()
        dc = _FakeDC()
        await s._deferred_boot_inject(dc)
        await s._deferred_boot_inject(dc)
        s._boot_inject_sync(dc, tag="extra")
        assert len(dc.sent) == 1

    asyncio.run(_run())


def test_dc_constants():
    assert DC_LABEL == "oai-events"
    assert DC_NEGOTIATED_ID == 0
    assert BOOT_INJECT_WAIT_S > 0


def test_topup_sends_exactly_one_plain():
    s = _session()
    dc = _FakeDC()
    s._dc = dc
    ok = s.push_context_live("New error: TypeError in wire_dc")
    assert ok is True
    assert len(dc.sent) == 1
    assert "WHAT'S NEW" in dc.sent[0]
    assert "TypeError" in dc.sent[0]
    # second topup is also one message (additive on wire, not multi-frame)
    ok2 = s.push_context_live("Now fixed negotiated id=0")
    assert ok2 is True
    assert len(dc.sent) == 2
    assert "WHAT'S NEW" in dc.sent[1]
