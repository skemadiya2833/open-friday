"""Stage V6: local performance snapshot (no network)."""

from __future__ import annotations

from friday.perf import finish_request, note_token, sample_gpu, snapshot, start_request


def test_start_finish_records_recent():
    ctx = start_request("chat", model="test-model")
    note_token(ctx, 3)
    m = finish_request(ctx)
    assert m.tokens == 3
    assert m.ttft_ms is not None
    snap = snapshot()
    assert snap["recent"]
    assert snap["recent"][0]["model"] == "test-model"
    assert "Local only" in snap["note"]


def test_sample_gpu_returns_struct():
    g = sample_gpu()
    assert g.source
    assert hasattr(g, "vram_used_mb")
