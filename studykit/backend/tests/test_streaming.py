"""Regression tests for the SSE streaming path.

These lock in the four defects that made mid-generation streaming fail while a
completed generation still worked:

1. every stream leaked a Valkey connection (`unsubscribe()` never releases it)
2. heartbeats were unreachable and the read loop busy-spun
3. a stale terminal `job_status` closed a fresh stream instantly
4. the limiter's exception class did not match the one slowapi raises
"""

import asyncio
import inspect
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from valkey.asyncio.client import PubSub

BACKEND = Path(__file__).resolve().parent.parent
MAIN_SRC = (BACKEND / "main.py").read_text(encoding="utf-8")


def _stream_source() -> str:
    """Source of the SSE endpoint, including its StreamingResponse."""
    start = MAIN_SRC.index("async def stream_questions")
    end = MAIN_SRC.index('@app.post("/sessions/{session_id}/generate"')
    return MAIN_SRC[start:end]


def _stream_generator_source() -> str:
    """Just the inner async generator, excluding the response construction."""
    src = _stream_source()
    return src[: src.index("return StreamingResponse")]


# ---------------------------------------------------------------------------
# 1. Connection leak
# ---------------------------------------------------------------------------


class TestPubSubConnectionRelease:
    async def test_unsubscribe_alone_does_not_release_connection(self):
        """Documents *why* aclose() is required — unsubscribe leaks."""
        released = []
        pool = MagicMock()
        conn = MagicMock()
        conn.send_command = AsyncMock()
        conn.connect = AsyncMock()
        conn.register_connect_callback = MagicMock()
        pool.get_connection = AsyncMock(return_value=conn)
        pool.release = AsyncMock(side_effect=released.append)

        pubsub = PubSub(pool)
        await pubsub.connect()
        try:
            await pubsub.unsubscribe("ch")
        except Exception:
            pass

        assert released == [], "valkey released on unsubscribe; test needs updating"
        assert pubsub.connection is not None, "connection is still checked out"

    async def test_aclose_releases_connection_back_to_pool(self):
        released = []
        pool = MagicMock()
        conn = MagicMock()
        conn.send_command = AsyncMock()
        conn.connect = AsyncMock()
        conn.disconnect = AsyncMock()
        conn.register_connect_callback = MagicMock()
        conn.deregister_connect_callback = MagicMock()
        pool.get_connection = AsyncMock(return_value=conn)
        pool.release = AsyncMock(side_effect=released.append)

        pubsub = PubSub(pool)
        await pubsub.connect()
        await pubsub.aclose()

        assert len(released) == 1
        assert pubsub.connection is None

    def test_stream_endpoint_closes_pubsub(self):
        src = _stream_source()
        assert "pubsub.aclose()" in src, (
            "SSE endpoint must call pubsub.aclose() or it leaks a Valkey "
            "connection per stream until subscribe() starts failing"
        )

    def test_subscribe_is_inside_try_so_failures_are_cleaned_up(self):
        src = _stream_source()
        subscribe_at = src.index("pubsub.subscribe(")
        try_at = src.index("\n        try:")
        assert try_at < subscribe_at, (
            "subscribe() must be inside the try block so a failure is logged "
            "and the connection is still released"
        )


# ---------------------------------------------------------------------------
# 2. Heartbeat / busy-spin
# ---------------------------------------------------------------------------


class TestHeartbeatAndPolling:
    def test_get_message_default_timeout_is_non_blocking(self):
        """The root cause: default timeout=0.0 returns immediately."""
        sig = inspect.signature(PubSub.get_message)
        assert sig.parameters["timeout"].default == 0.0

    async def test_wait_for_around_default_get_message_never_times_out(self):
        """Why the old heartbeat branch was unreachable."""

        class Immediate:
            async def get_message(self, ignore_subscribe_messages=True, timeout=0.0):
                return None

        ps = Immediate()
        timed_out = False
        try:
            await asyncio.wait_for(
                ps.get_message(ignore_subscribe_messages=True), timeout=0.05
            )
        except asyncio.TimeoutError:
            timed_out = True

        assert not timed_out, (
            "wait_for cannot time out a non-blocking call, so the heartbeat "
            "branch never ran and the loop busy-spun"
        )

    def test_stream_passes_timeout_to_get_message(self):
        src = _stream_source()
        calls = re.findall(r"get_message\((.*?)\)", src, re.S)
        assert calls, "expected get_message calls in the SSE endpoint"
        for args in calls:
            assert "timeout" in args, (
                "every get_message call must pass an explicit timeout; "
                "the 0.0 default busy-spins"
            )

    def test_stream_does_not_wrap_get_message_in_wait_for(self):
        # Strip comments so the explanatory note about wait_for doesn't match.
        code = "\n".join(
            line.split("#", 1)[0]
            for line in _stream_generator_source().splitlines()
        )
        assert "wait_for" not in code, (
            "asyncio.wait_for around get_message never fires and cancelling a "
            "pending read can desynchronise the pubsub connection"
        )

    def test_heartbeat_is_reachable_on_idle_reads(self):
        src = _stream_source()
        idx = src.index("event: heartbeat")
        assert "except asyncio.TimeoutError" not in src[:idx], (
            "heartbeat must not live in a TimeoutError branch"
        )
        assert "if message is None:" in src, (
            "heartbeat should be emitted when a read returns no message"
        )


# ---------------------------------------------------------------------------
# 3. Stale job_status race
# ---------------------------------------------------------------------------


class TestStaleJobStatus:
    def test_generate_clears_job_status_on_enqueue(self):
        start = MAIN_SRC.index("@app.post(\"/sessions/{session_id}/generate\"")
        src = MAIN_SRC[start : start + 3000]
        assert 'delete(f"job_status:{session_id}")' in src, (
            "generate must clear job_status when enqueuing; a terminal status "
            "from a previous run (ex=3600) otherwise closes the new stream "
            "immediately with zero questions"
        )

    async def test_stale_terminal_status_would_end_stream_immediately(self):
        """Demonstrates the race the fix prevents."""
        TERMINAL = ("generated", "failed_validation", "failed")
        stale_status = "generated"  # left by the previous run, TTL 1h
        assert stale_status in TERMINAL

        emitted = []
        if stale_status and stale_status in TERMINAL:
            emitted.append("job_complete")
        assert emitted == ["job_complete"], "stream would close before any question"


# ---------------------------------------------------------------------------
# 4. Rate limiter wiring
# ---------------------------------------------------------------------------


class TestRateLimiterWiring:
    def test_handler_registered_for_the_class_slowapi_raises(self):
        from slowapi.errors import RateLimitExceeded as SlowAPIError

        import exceptions

        assert exceptions.RateLimitExceeded is not SlowAPIError, (
            "these are deliberately different classes"
        )
        assert "from slowapi.errors import RateLimitExceeded" in MAIN_SRC, (
            "main must import the class slowapi actually raises"
        )
        assert "@app.exception_handler(SlowAPIRateLimitExceeded)" in MAIN_SRC, (
            "a handler must be registered for slowapi's RateLimitExceeded, "
            "otherwise the custom handler is dead code"
        )

    def test_rate_limit_key_prefers_cloudflare_client_ip(self):
        import main

        req = MagicMock()
        req.headers = {"CF-Connecting-IP": "203.0.113.9"}
        assert main.client_ip(req) == "203.0.113.9"

    def test_rate_limit_key_falls_back_to_forwarded_for(self):
        import main

        req = MagicMock()
        req.headers = {"X-Forwarded-For": "198.51.100.4, 172.16.0.1"}
        assert main.client_ip(req) == "198.51.100.4"


# ---------------------------------------------------------------------------
# 5. Streaming response headers
# ---------------------------------------------------------------------------


class TestStreamHeaders:
    @pytest.mark.parametrize(
        "header", ["text/event-stream", "no-cache", "X-Accel-Buffering"]
    )
    def test_sse_headers_present(self, header):
        src = _stream_source()
        assert header in src, f"SSE response should set {header}"
