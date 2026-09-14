import asyncio
import logging

from app.core.database import SessionLocal
from app.services.microsoft365_inbound import sync_enabled_inboxes


logger = logging.getLogger(__name__)


def sync_once() -> tuple[int, int]:
    with SessionLocal() as db:
        result = sync_enabled_inboxes(db)
    return (
        sum(item["seen"] for item in result.values()),
        sum(item["created"] for item in result.values()),
    )


async def run_microsoft365_sync_loop(
    stop: asyncio.Event, *, interval_seconds: int
) -> None:
    interval = max(interval_seconds, 30)
    while not stop.is_set():
        try:
            seen, created = await asyncio.to_thread(sync_once)
            logger.info(
                "Microsoft 365 inbox sync complete: %s seen, %s created.",
                seen,
                created,
            )
        except Exception:
            logger.exception("Microsoft 365 inbox sync failed; retrying after interval.")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
