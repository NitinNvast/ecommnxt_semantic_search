import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.config import settings
from app.worker.outbox_processor import poll_outbox
from app.worker.reconcile import reconcile_all

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def start_scheduler() -> None:
    scheduler = get_scheduler()
    scheduler.add_job(
        poll_outbox,
        trigger=IntervalTrigger(seconds=settings.OUTBOX_POLL_INTERVAL),
        id="poll_outbox",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        reconcile_all,
        trigger=CronTrigger(hour=settings.RECONCILE_HOUR, minute=0),
        id="reconcile_all",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started — poll_outbox every %ds, reconcile_all daily at %02d:00",
        settings.OUTBOX_POLL_INTERVAL,
        settings.RECONCILE_HOUR,
    )


def stop_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
