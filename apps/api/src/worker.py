"""
Celery Worker Configuration
"""

from celery import Celery
from celery.signals import worker_init, worker_process_init

from src.core.config import settings

# Ensure Celery soft/hard limits are always valid even with small SLA values.
task_time_limit = max(60, int(settings.job_sla_seconds))
task_soft_time_limit = max(30, task_time_limit - 30)

# Create Celery app
celery_app = Celery(
    "storybook",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Seoul",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=task_time_limit,
    task_soft_time_limit=task_soft_time_limit,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["src.services"])


@worker_init.connect
@worker_process_init.connect
def _configure_worker_database(**_kwargs) -> None:
    """워커 프로세스의 async 엔진을 NullPool 로 재구성한다(C1).

    두 신호를 모두 받는 이유: `worker_process_init` 은 prefork 자식에서만,
    `worker_init` 은 (solo/threads 포함) 메인 워커 프로세스에서 발화한다. 어느 풀로
    기동해도 태스크를 실제로 실행하는 프로세스가 반드시 재구성되게 한다.
    `configure_for_worker()` 는 멱등이라 둘 다 발화해도 안전하다.
    """
    from src.core.database import configure_for_worker

    configure_for_worker()
