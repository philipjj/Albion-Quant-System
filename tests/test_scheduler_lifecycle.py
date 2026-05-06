from __future__ import annotations

import asyncio


def test_scheduler_stop_then_start_resumes_without_duplicate_jobs() -> None:
    """Regression: stop() only pauses; a second start() must resume, not re-add_job."""

    async def body() -> None:
        from workers.scheduler import QuantScheduler

        s = QuantScheduler()
        s.start()
        assert s._is_running
        n_jobs = len(s.scheduler.get_jobs())
        assert n_jobs >= 1

        s.stop()
        assert not s._is_running

        s.start()
        assert s._is_running
        assert len(s.scheduler.get_jobs()) == n_jobs

        s.scheduler.shutdown(wait=False)

    asyncio.run(body())
