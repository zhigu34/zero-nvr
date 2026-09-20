from __future__ import annotations


class FrigateTaskDispatcher:
    """Thin Huey enqueue boundary for Frigate recovery work."""

    @staticmethod
    def backfill(
        *,
        lookback_seconds: int = 600,
    ) -> None:
        from app.worker.tasks import backfill_frigate_events

        backfill_frigate_events(lookback_seconds)
