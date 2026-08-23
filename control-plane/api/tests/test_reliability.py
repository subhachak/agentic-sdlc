import pytest

from app.core.reliability import with_retry_fallback


@pytest.mark.asyncio
async def test_succeeds_without_retry_when_node_works():
    calls = []

    async def node(state):
        calls.append(1)
        return {"ok": True}

    wrapped = with_retry_fallback("n", lambda s: {"ok": False}, max_retries=2)(node)
    result = await wrapped({})
    assert result == {"ok": True}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_retries_then_succeeds():
    attempts = {"count": 0}

    async def node(state):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("transient")
        return {"ok": True}

    wrapped = with_retry_fallback("n", lambda s: {"ok": False}, max_retries=3)(node)
    result = await wrapped({})
    assert result == {"ok": True}
    assert attempts["count"] == 3


@pytest.mark.asyncio
async def test_falls_back_to_template_after_exhausting_retries():
    async def node(state):
        raise RuntimeError("always fails")

    wrapped = with_retry_fallback("n", lambda s: {"status": "fallback_used"}, max_retries=2)(node)
    result = await wrapped({})
    assert result["status"] == "fallback_used"
    assert result["_reliability_fallback_used"] is True


@pytest.mark.asyncio
async def test_max_retries_zero_still_tries_once_before_falling_back():
    attempts = {"count": 0}

    async def node(state):
        attempts["count"] += 1
        raise RuntimeError("fails")

    wrapped = with_retry_fallback("n", lambda s: {"status": "fallback"}, max_retries=0)(node)
    result = await wrapped({})
    assert attempts["count"] == 1
    assert result["status"] == "fallback"
