from __future__ import annotations

from app.rate_limit import RequestLimiter


def test_token_bucket_enforces_burst_and_refills_over_time():
    limiter = RequestLimiter(burst=2, refill_seconds=10, daily_limit=20)

    assert limiter.consume("client", now=100) == (True, 0)
    assert limiter.consume("client", now=100) == (True, 0)
    allowed, retry_after = limiter.consume("client", now=100)
    assert not allowed
    assert retry_after == 5
    assert limiter.consume("client", now=105) == (True, 0)


def test_limiter_enforces_global_daily_cap():
    limiter = RequestLimiter(burst=10, refill_seconds=60, daily_limit=1)

    assert limiter.consume("first", now=1) == (True, 0)
    allowed, retry_after = limiter.consume("second", now=1)

    assert not allowed
    assert retry_after > 0

