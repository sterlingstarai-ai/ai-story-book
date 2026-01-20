"""
Celery tasks for async book generation
"""
import asyncio
from celery import shared_task
import structlog


logger = structlog.get_logger()


def run_async(coro):
    """Run async function in sync context for Celery."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(bind=True, max_retries=0)
def generate_book_task(self, job_id: str, spec_dict: dict, user_key: str):
    """
    Celery task for book generation.

    Args:
        job_id: Job ID
        spec_dict: BookSpec as dictionary
        user_key: User key
    """
    logger.info("Starting book generation task", job_id=job_id)

    try:
        from src.services.orchestrator import orchestrate_book_creation
        from src.models.dto import BookSpec

        spec = BookSpec(**spec_dict)
        result = run_async(orchestrate_book_creation(job_id, spec, user_key))

        logger.info("Book generation completed", job_id=job_id)
        return {"status": "success", "book_id": result.book_id if result else None}

    except Exception as e:
        logger.error("Book generation failed", job_id=job_id, error=str(e))
        # Update job status to failed
        try:
            from src.core.database import SessionLocal
            from src.models.db import Job

            with SessionLocal() as session:
                job = session.query(Job).filter(Job.id == job_id).first()
                if job:
                    job.status = "failed"
                    job.error_message = str(e)[:300]
                    session.commit()
        except Exception as db_error:
            logger.error("Failed to update job status", error=str(db_error))

        raise


@shared_task(bind=True, max_retries=2)
def regenerate_page_task(
    self,
    job_id: str,
    page_number: int,
    target: str,
    user_key: str,
):
    """
    Celery task for page regeneration.

    Args:
        job_id: Job ID
        page_number: Page number (1-indexed)
        target: Regeneration target ('text', 'image', 'both')
        user_key: User key
    """
    logger.info(
        "Starting page regeneration task",
        job_id=job_id,
        page_number=page_number,
        target=target,
    )

    try:
        from src.services.orchestrator import regenerate_page

        result = run_async(regenerate_page(job_id, page_number, target, user_key))
        logger.info("Page regeneration completed", job_id=job_id, page_number=page_number)
        return {"status": "success", "result": result}

    except Exception as e:
        logger.error(
            "Page regeneration failed",
            job_id=job_id,
            page_number=page_number,
            error=str(e),
        )
        raise self.retry(exc=e, countdown=5)
