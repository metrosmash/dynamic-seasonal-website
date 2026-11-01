from __future__ import annotations

import threading
import time
from datetime import datetime, timezone


class RequestLimiter:
    def __init__(
        self,
        *,
        burst: int = 10,
        refill_seconds: int = 60,
        daily_limit: int = 5000,
    ) -> None:
        self.burst = burst
        self.refill_rate = burst / refill_seconds
        self.daily_limit = daily_limit
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}
        self._max_identities = 10_000
        self._daily_count = 0
        self._utc_day = datetime.now(timezone.utc).date()

    def consume(self, identity: str, now: float | None = None) -> tuple[bool, int]:
        current = time.monotonic() if now is None else now
        today = datetime.now(timezone.utc).date()
        with self._lock:
            if today != self._utc_day:
                self._utc_day = today
                self._daily_count = 0
            if self._daily_count >= self.daily_limit:
                return False, 60
            if identity not in self._buckets and len(self._buckets) >= self._max_identities:
                expired = [
                    key for key, (available, updated) in self._buckets.items()
                    if available + max(0, current - updated) * self.refill_rate >= self.burst
                ]
                for key in expired:
                    self._buckets.pop(key, None)
                if len(self._buckets) >= self._max_identities:
                    oldest = next(iter(self._buckets))
                    self._buckets.pop(oldest, None)
            tokens, last_update = self._buckets.get(identity, (float(self.burst), current))
            tokens = min(self.burst, tokens + max(0, current - last_update) * self.refill_rate)
            if tokens < 1:
                wait = max(1, int((1 - tokens) / self.refill_rate + 0.999))
                self._buckets[identity] = (tokens, current)
                return False, wait
            self._buckets[identity] = (tokens - 1, current)
            self._daily_count += 1
            return True, 0
