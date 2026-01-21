"""
Celery Worker Configuration
"""

from celery import Celery

from src.core.config import settings

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
    task_time_limit=settings.job_sla_seconds,
    task_soft_time_limit=settings.job_sla_seconds - 60,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["src.services"])
