"""What the daemon does *for* its clients beyond answering requests.

The daemon is the one process every agent, the GUI and the CLI share, which makes it the
only place that can see, and pace, their combined load:

* ``RequestStats`` — how busy it is and which requests were slow (``/admin/status``).
* ``SlotLimiter`` — one rate limiter for the external APIs. Each CLI process used to keep
  its own timer, so five agents each sent ten requests a second against a ten-a-second limit.
* ``fts_worker`` — rebuilds the full-text index once writes go quiet, instead of every write.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque

from scopus_for_dobby.core import article_db as adb

logger = logging.getLogger(__name__)


class RequestStats:
    """Counters and a short list of recent slow requests. Cheap enough to run always."""

    def __init__(self, slow_after: float = 1.0, keep: int = 20):
        self.slow_after = slow_after
        self.started = time.time()
        self.total = 0
        self.in_flight = 0
        self.by_status: dict[str, int] = {}
        self.slow: deque[dict] = deque(maxlen=keep)
        self._lock = threading.Lock()

    def begin(self) -> None:
        with self._lock:
            self.in_flight += 1

    def end(self, method: str, path: str, status: int, seconds: float) -> bool:
        """Record a finished request. True if it was slow."""
        is_slow = seconds >= self.slow_after
        with self._lock:
            self.in_flight -= 1
            self.total += 1
            key = f"{status // 100}xx"
            self.by_status[key] = self.by_status.get(key, 0) + 1
            if is_slow:
                self.slow.append(
                    {
                        "at": time.strftime("%H:%M:%S"),
                        "method": method,
                        "path": path,
                        "status": status,
                        "seconds": round(seconds, 2),
                    }
                )
        return is_slow

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "total": self.total,
                "in_flight": self.in_flight,
                "by_status": dict(self.by_status),
                "slow_after_s": self.slow_after,
                "slow_recent": list(self.slow),
            }


class SlotLimiter:
    """Hands out request slots so that *all* processes together respect an API's rate.

    A client asks "when may I send to this endpoint?" and sleeps for the answer. A slot is
    reserved at the moment of asking, so ten processes asking at once get ten consecutive
    slots rather than ten identical answers.
    """

    def __init__(self, intervals: dict[str, float]):
        self._intervals = intervals
        self._next: dict[str, float] = {}
        self._granted: dict[str, int] = {}
        self._lock = threading.Lock()

    def reserve(self, endpoint: str) -> float:
        """Seconds the caller must wait before sending to ``endpoint`` (0 if unlimited)."""
        for prefix, interval in self._intervals.items():
            if prefix in endpoint:
                with self._lock:
                    now = time.monotonic()
                    start = max(now, self._next.get(prefix, 0.0))
                    self._next[prefix] = start + interval
                    self._granted[prefix] = self._granted.get(prefix, 0) + 1
                    return start - now
        return 0.0

    def snapshot(self) -> dict:
        with self._lock:
            now = time.monotonic()
            return {
                prefix: {
                    "interval_s": interval,
                    "granted": self._granted.get(prefix, 0),
                    "queued_s": round(max(0.0, self._next.get(prefix, 0.0) - now), 2),
                }
                for prefix, interval in self._intervals.items()
                if prefix in self._granted
            }


async def fts_worker(debounce: float, max_wait: float, poll: float) -> None:
    """Rebuild the full-text index once, after writes have been quiet for ``debounce`` s.

    Writes only mark the index stale (see ``article_db.fts_status``). This watches for that
    and rebuilds at most once per burst, but never lets it go more than ``max_wait`` s
    behind during a long one. The rebuild runs in a thread so the event loop keeps serving.
    """
    first_dirty: float | None = None
    last_change = 0.0
    last_latest = -1
    while True:
        await asyncio.sleep(poll)
        try:
            status = await asyncio.to_thread(adb.fts_status)
        except Exception:
            logger.exception("FTS status check failed")
            continue
        if not status["stale"]:
            first_dirty = None
            continue
        now = time.monotonic()
        if first_dirty is None:
            first_dirty, last_change = now, now
            last_latest = status["latest_event_id"]
        elif status["latest_event_id"] != last_latest:
            last_latest, last_change = status["latest_event_id"], now
        if now - last_change < debounce and now - first_dirty < max_wait:
            continue
        try:
            result = await asyncio.to_thread(adb.ensure_fts_fresh)
            if result.get("rebuilt"):
                logger.info("background FTS rebuild: %s", result)
        except Exception:
            logger.exception("background FTS rebuild failed; will retry")
            await asyncio.sleep(max(poll, 30.0))
        first_dirty = None
