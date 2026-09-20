from __future__ import annotations

from app.modules.auth.rate_limit import AuthRateLimiter


def test_rate_limiter_backoff_expires_and_success_clears_pair() -> None:
    current = [100.0]
    limiter = AuthRateLimiter(
        clock=lambda: current[0],
        login_pair_limit=2,
        login_ip_limit=10,
        login_lockout_seconds=30,
        reset_ip_limit=2,
        reset_lockout_seconds=20,
    )

    assert limiter.check_login(
        source_ip="192.0.2.1",
        identifier="Admin",
    ).allowed

    assert limiter.record_login_failure(
        source_ip="192.0.2.1",
        identifier="Admin",
    ).allowed

    blocked = limiter.record_login_failure(
        source_ip="192.0.2.1",
        identifier="admin",
    )
    assert blocked.allowed is False
    assert blocked.newly_blocked is True
    assert blocked.retry_after_seconds == 30

    current[0] = 131.0
    assert limiter.check_login(
        source_ip="192.0.2.1",
        identifier="admin",
    ).allowed

    limiter.record_login_failure(
        source_ip="192.0.2.1",
        identifier="admin",
    )
    limiter.record_login_success(
        source_ip="192.0.2.1",
        identifier="admin",
    )
    assert limiter.check_login(
        source_ip="192.0.2.1",
        identifier="admin",
    ).allowed

    assert limiter.consume_password_reset(
        source_ip="192.0.2.2"
    ).allowed
    assert limiter.consume_password_reset(
        source_ip="192.0.2.2"
    ).allowed
    reset_blocked = limiter.consume_password_reset(
        source_ip="192.0.2.2"
    )
    assert reset_blocked.allowed is False
    assert reset_blocked.newly_blocked is True

    current[0] = 152.0
    assert limiter.consume_password_reset(
        source_ip="192.0.2.2"
    ).allowed
