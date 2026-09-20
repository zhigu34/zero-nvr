from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import threading
import time
from typing import Callable


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0
    newly_blocked: bool = False


class AuthRateLimiter:
    """Short-lived in-process brute-force protection for the API process."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        login_window_seconds: int = 300,
        login_pair_limit: int = 5,
        login_ip_limit: int = 20,
        login_lockout_seconds: int = 300,
        reset_window_seconds: int = 60,
        reset_ip_limit: int = 10,
        reset_lockout_seconds: int = 60,
        max_keys: int = 4096,
    ) -> None:
        self._clock = clock
        self.login_window_seconds = login_window_seconds
        self.login_pair_limit = login_pair_limit
        self.login_ip_limit = login_ip_limit
        self.login_lockout_seconds = login_lockout_seconds
        self.reset_window_seconds = reset_window_seconds
        self.reset_ip_limit = reset_ip_limit
        self.reset_lockout_seconds = reset_lockout_seconds
        self.max_keys = max_keys

        self._login_pair: dict[
            tuple[str, str],
            deque[float],
        ] = {}
        self._login_ip: dict[str, deque[float]] = {}
        self._login_blocked_pair: dict[
            tuple[str, str],
            float,
        ] = {}
        self._login_blocked_ip: dict[str, float] = {}
        self._reset_ip: dict[str, deque[float]] = {}
        self._reset_blocked_ip: dict[str, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _source(value: str | None) -> str:
        return (value or "unknown")[:64]

    @staticmethod
    def _identifier(value: str) -> str:
        return value.strip().casefold()[:320]

    @staticmethod
    def _prune(
        bucket: deque[float],
        *,
        now: float,
        window: int,
    ) -> None:
        cutoff = now - window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def _cap(self, mapping: dict) -> None:
        while len(mapping) > self.max_keys:
            mapping.pop(next(iter(mapping)))

    @staticmethod
    def _blocked_decision(
        *,
        now: float,
        blocked_until: float,
    ) -> RateLimitDecision:
        return RateLimitDecision(
            allowed=False,
            retry_after_seconds=max(
                1,
                int(math.ceil(blocked_until - now)),
            ),
        )

    def check_login(
        self,
        *,
        source_ip: str | None,
        identifier: str,
    ) -> RateLimitDecision:
        source = self._source(source_ip)
        pair = (source, self._identifier(identifier))
        now = self._clock()

        with self._lock:
            pair_until = self._login_blocked_pair.get(
                pair,
                0.0,
            )
            ip_until = self._login_blocked_ip.get(
                source,
                0.0,
            )
            blocked_until = max(pair_until, ip_until)
            if blocked_until > now:
                return self._blocked_decision(
                    now=now,
                    blocked_until=blocked_until,
                )

            if pair_until:
                self._login_blocked_pair.pop(pair, None)
                self._login_pair.pop(pair, None)
            if ip_until:
                self._login_blocked_ip.pop(source, None)
                self._login_ip.pop(source, None)
            return RateLimitDecision(allowed=True)

    def record_login_failure(
        self,
        *,
        source_ip: str | None,
        identifier: str,
    ) -> RateLimitDecision:
        source = self._source(source_ip)
        pair = (source, self._identifier(identifier))
        now = self._clock()

        with self._lock:
            pair_bucket = self._login_pair.setdefault(
                pair,
                deque(),
            )
            ip_bucket = self._login_ip.setdefault(
                source,
                deque(),
            )
            self._prune(
                pair_bucket,
                now=now,
                window=self.login_window_seconds,
            )
            self._prune(
                ip_bucket,
                now=now,
                window=self.login_window_seconds,
            )
            pair_bucket.append(now)
            ip_bucket.append(now)

            newly_blocked = False
            blocked_until = 0.0

            if len(pair_bucket) >= self.login_pair_limit:
                candidate = (
                    now + self.login_lockout_seconds
                )
                if self._login_blocked_pair.get(
                    pair,
                    0.0,
                ) <= now:
                    newly_blocked = True
                self._login_blocked_pair[pair] = candidate
                blocked_until = max(
                    blocked_until,
                    candidate,
                )

            if len(ip_bucket) >= self.login_ip_limit:
                candidate = (
                    now + self.login_lockout_seconds
                )
                if self._login_blocked_ip.get(
                    source,
                    0.0,
                ) <= now:
                    newly_blocked = True
                self._login_blocked_ip[source] = candidate
                blocked_until = max(
                    blocked_until,
                    candidate,
                )

            self._cap(self._login_pair)
            self._cap(self._login_ip)
            self._cap(self._login_blocked_pair)
            self._cap(self._login_blocked_ip)

            if blocked_until > now:
                base = self._blocked_decision(
                    now=now,
                    blocked_until=blocked_until,
                )
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=(
                        base.retry_after_seconds
                    ),
                    newly_blocked=newly_blocked,
                )

            return RateLimitDecision(allowed=True)

    def record_login_success(
        self,
        *,
        source_ip: str | None,
        identifier: str,
    ) -> None:
        source = self._source(source_ip)
        pair = (source, self._identifier(identifier))
        with self._lock:
            self._login_pair.pop(pair, None)
            self._login_blocked_pair.pop(pair, None)

    def consume_password_reset(
        self,
        *,
        source_ip: str | None,
    ) -> RateLimitDecision:
        source = self._source(source_ip)
        now = self._clock()

        with self._lock:
            blocked_until = self._reset_blocked_ip.get(
                source,
                0.0,
            )
            if blocked_until > now:
                return self._blocked_decision(
                    now=now,
                    blocked_until=blocked_until,
                )
            if blocked_until:
                self._reset_blocked_ip.pop(source, None)
                self._reset_ip.pop(source, None)

            bucket = self._reset_ip.setdefault(
                source,
                deque(),
            )
            self._prune(
                bucket,
                now=now,
                window=self.reset_window_seconds,
            )
            if len(bucket) >= self.reset_ip_limit:
                blocked_until = (
                    now + self.reset_lockout_seconds
                )
                self._reset_blocked_ip[source] = (
                    blocked_until
                )
                self._cap(self._reset_blocked_ip)
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=(
                        self.reset_lockout_seconds
                    ),
                    newly_blocked=True,
                )

            bucket.append(now)
            self._cap(self._reset_ip)
            return RateLimitDecision(allowed=True)
