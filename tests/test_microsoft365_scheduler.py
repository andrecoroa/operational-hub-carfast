import asyncio

import app.services.microsoft365_scheduler as scheduler


def test_sync_once_summarizes_all_transports(monkeypatch):
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(scheduler, "SessionLocal", Session)
    monkeypatch.setattr(
        scheduler,
        "sync_enabled_inboxes",
        lambda db: {1: {"seen": 2, "created": 1}, 2: {"seen": 3, "created": 2}},
    )

    assert scheduler.sync_once() == (5, 3)


def test_loop_runs_immediately_and_stops(monkeypatch):
    calls = []

    def fake_sync_once():
        calls.append(True)
        return 0, 0

    monkeypatch.setattr(scheduler, "sync_once", fake_sync_once)

    async def exercise():
        stop = asyncio.Event()
        task = asyncio.create_task(
            scheduler.run_microsoft365_sync_loop(stop, interval_seconds=30)
        )
        while not calls:
            await asyncio.sleep(0)
        stop.set()
        await task

    asyncio.run(exercise())
    assert calls == [True]
