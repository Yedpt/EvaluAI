"""In-memory cooldown and rate-limit guards for evaluation creation."""

from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
import time


@dataclass
class GuardResult:
    allowed: bool
    retry_after_seconds: int = 0


class EvaluationAbuseGuard:
    """Best-effort, process-local abuse guard for evaluation endpoints."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._request_timestamps = defaultdict(deque)
        self._last_default_provider_eval = {}

    def check_rate_limit(self, client_id: str, max_requests: int, window_seconds: int) -> GuardResult:
        now = time.time()
        with self._lock:
            bucket = self._request_timestamps[client_id]

            # Trim stale entries out of the rolling window.
            while bucket and (now - bucket[0]) > window_seconds:
                bucket.popleft()

            if len(bucket) >= max_requests:
                retry_after = max(1, int(window_seconds - (now - bucket[0])))
                return GuardResult(allowed=False, retry_after_seconds=retry_after)

            bucket.append(now)
            return GuardResult(allowed=True)

    def check_default_provider_cooldown(self, client_id: str, cooldown_seconds: int) -> GuardResult:
        now = time.time()
        with self._lock:
            last = self._last_default_provider_eval.get(client_id)
            if last is None:
                return GuardResult(allowed=True)

            elapsed = int(now - last)
            if elapsed >= cooldown_seconds:
                return GuardResult(allowed=True)

            return GuardResult(allowed=False, retry_after_seconds=cooldown_seconds - elapsed)

    def register_default_provider_usage(self, client_id: str) -> None:
        with self._lock:
            self._last_default_provider_eval[client_id] = time.time()

    def get_default_provider_remaining_seconds(self, client_id: str, cooldown_seconds: int) -> int:
        with self._lock:
            last = self._last_default_provider_eval.get(client_id)
            if last is None:
                return 0

            remaining = cooldown_seconds - int(time.time() - last)
            return max(0, remaining)


guard = EvaluationAbuseGuard()
