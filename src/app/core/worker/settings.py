from arq.connections import RedisSettings
from arq.cron import cron

from ...core.config import settings
from .functions import sample_background_task, check_and_run_recurring_campaigns, shutdown, startup

REDIS_QUEUE_HOST = settings.REDIS_QUEUE_HOST
REDIS_QUEUE_PORT = settings.REDIS_QUEUE_PORT


class WorkerSettings:
    functions = [sample_background_task]
    redis_settings = RedisSettings(host=REDIS_QUEUE_HOST, port=REDIS_QUEUE_PORT)
    on_startup = startup
    on_shutdown = shutdown
    handle_signals = False

    # Cron jobs - check for recurring campaigns every hour
    cron_jobs = [
        cron(check_and_run_recurring_campaigns, hour={0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}, minute=0, unique=True)
    ]
