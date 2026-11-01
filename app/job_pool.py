from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, TypeVar


T = TypeVar("T")


class BoundedJobPool:
    def __init__(self, *, workers: int = 2, max_pending: int = 8) -> None:
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="halloween-job")
        self._slots = threading.BoundedSemaphore(max_pending)

    def submit(self, function: Callable[[], T]) -> Future[T] | None:
        if not self._slots.acquire(blocking=False):
            return None
        try:
            future = self._executor.submit(function)
        except RuntimeError:
            self._slots.release()
            raise
        future.add_done_callback(lambda _future: self._slots.release())
        return future

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)
