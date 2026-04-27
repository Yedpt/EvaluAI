"""Unit tests for in-memory abuse protection guard."""

import time

from services.abuse_protection import EvaluationAbuseGuard


class TestEvaluationAbuseGuard:
    def test_rate_limit_allows_within_window(self):
        guard = EvaluationAbuseGuard()

        for _ in range(3):
            result = guard.check_rate_limit("client-a", max_requests=3, window_seconds=60)
            assert result.allowed is True

    def test_rate_limit_blocks_excess(self):
        guard = EvaluationAbuseGuard()

        guard.check_rate_limit("client-a", max_requests=1, window_seconds=60)
        blocked = guard.check_rate_limit("client-a", max_requests=1, window_seconds=60)

        assert blocked.allowed is False
        assert blocked.retry_after_seconds > 0

    def test_default_provider_cooldown(self):
        guard = EvaluationAbuseGuard()

        initial = guard.check_default_provider_cooldown("client-a", cooldown_seconds=5)
        assert initial.allowed is True

        guard.register_default_provider_usage("client-a")

        blocked = guard.check_default_provider_cooldown("client-a", cooldown_seconds=5)
        assert blocked.allowed is False
        assert blocked.retry_after_seconds > 0

    def test_default_provider_remaining_reaches_zero(self):
        guard = EvaluationAbuseGuard()

        guard.register_default_provider_usage("client-a")
        remaining = guard.get_default_provider_remaining_seconds("client-a", cooldown_seconds=1)
        assert remaining in (0, 1)

        time.sleep(1.1)
        remaining_after = guard.get_default_provider_remaining_seconds("client-a", cooldown_seconds=1)
        assert remaining_after == 0
