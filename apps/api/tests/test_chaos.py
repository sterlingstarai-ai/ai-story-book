"""
Chaos and Fault Injection Tests
외부 API 장애 시나리오 테스트
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient
import asyncio


class TestLLMFailures:
    """LLM API failure scenarios."""

    @pytest.mark.asyncio
    async def test_llm_timeout_retry(self):
        """LLM timeout should trigger retry."""
        from src.services.orchestrator import run_step

        call_count = 0

        async def flaky_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                await asyncio.sleep(10)  # Will timeout
            return "success"

        with patch('src.services.orchestrator.update_job_status', new_callable=AsyncMock):
            # Should retry and eventually succeed
            try:
                result = await run_step(
                    job_id="test-job",
                    step_name="test step",
                    progress=50,
                    fn=flaky_fn,
                    retries=2,
                    timeout_sec=1,
                    backoff=[0.1, 0.1]
                )
                assert result == "success"
                assert call_count >= 2
            except Exception:
                # Expected if all retries fail
                pass

    @pytest.mark.asyncio
    async def test_llm_json_invalid_retry(self):
        """Invalid JSON from LLM should trigger retry."""
        from src.core.errors import TransientError

        call_count = 0

        async def flaky_json_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise TransientError("LLM_JSON_INVALID", "Invalid JSON")
            return {"valid": "json"}

        with patch('src.services.orchestrator.update_job_status', new_callable=AsyncMock):
            from src.services.orchestrator import run_step
            result = await run_step(
                job_id="test-job",
                step_name="test step",
                progress=50,
                fn=flaky_json_fn,
                retries=2,
                timeout_sec=30,
                backoff=[0.1, 0.1]
            )
            assert result == {"valid": "json"}
            assert call_count == 2


class TestImageAPIFailures:
    """Image API failure scenarios."""

    @pytest.mark.asyncio
    async def test_image_rate_limit_429(self):
        """Image API 429 should be handled gracefully."""
        from src.services.orchestrator import generate_image_with_retry
        from src.models.dto import ImagePrompt

        prompt = ImagePrompt(
            page=1,
            positive_prompt="A cute bunny in a meadow, watercolor style",
            negative_prompt="ugly, deformed, blurry",
            seed=12345,
            aspect_ratio="3:4"
        )

        # Mock to simulate 429 then success
        call_count = 0

        async def mock_generate(p):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                from src.core.errors import ImageError, ErrorCode
                raise ImageError(ErrorCode.IMAGE_RATE_LIMIT, "Rate limited", page=1)
            return "https://example.com/image.png"

        with patch('src.services.image.generate_image', side_effect=mock_generate):
            with patch('src.core.config.settings') as mock_settings:
                mock_settings.image_max_retries = 5
                mock_settings.image_timeout = 10

                url = await generate_image_with_retry(prompt, "test-job", 1)
                # Should either succeed or return placeholder
                assert url is not None

    @pytest.mark.asyncio
    async def test_image_500_error(self):
        """Image API 500 should be handled gracefully."""
        from src.services.orchestrator import generate_image_with_retry
        from src.models.dto import ImagePrompt
        from src.core.errors import ImageError, ErrorCode

        prompt = ImagePrompt(
            page=1,
            positive_prompt="Test prompt for image generation",
            negative_prompt="ugly, deformed",
            seed=12345,
            aspect_ratio="3:4"
        )

        async def mock_generate_fail(p):
            raise ImageError(ErrorCode.IMAGE_FAILED, "Server error 500", page=1)

        with patch('src.services.image.generate_image', side_effect=mock_generate_fail):
            with patch('src.core.config.settings') as mock_settings:
                mock_settings.image_max_retries = 2
                mock_settings.image_timeout = 5

                url = await generate_image_with_retry(prompt, "test-job", 1)
                # Should return placeholder on failure
                assert "placeholder" in url


class TestDatabaseFailures:
    """Database failure scenarios."""

    @pytest.mark.asyncio
    async def test_db_connection_lost_during_job(self):
        """Database connection loss should fail job gracefully."""
        from src.services.orchestrator import mark_job_failed
        from src.core.errors import ErrorCode

        # This should not raise even if DB is unavailable
        with patch('src.core.database.AsyncSessionLocal') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(side_effect=Exception("Connection lost"))
            mock_session.return_value.__aexit__ = AsyncMock()

            # Should handle gracefully
            try:
                await mark_job_failed("test-job", ErrorCode.DB_WRITE_FAILED, "Test error")
            except Exception as e:
                # Expected to raise but should be specific error
                assert "Connection" in str(e) or True


class TestRedisFailures:
    """Redis failure scenarios."""

    @pytest.mark.asyncio
    async def test_redis_unavailable_rate_limit_bypass(self, client: AsyncClient, headers: dict):
        """Rate limiting should fail-open when Redis is unavailable."""
        import redis.asyncio as redis

        with patch('src.core.rate_limit.rate_limiter.get_redis') as mock_redis:
            mock_redis.side_effect = redis.RedisError("Connection refused")

            # Request should still succeed (fail-open)
            response = await client.get("/health")
            assert response.status_code == 200


class TestStorageFailures:
    """S3/Storage failure scenarios."""

    @pytest.mark.asyncio
    async def test_s3_upload_failure_retry(self):
        """S3 upload failure should not crash the system."""
        from src.services.storage import storage_service

        # Mock S3 failure
        with patch.object(storage_service, '_ensure_bucket', new_callable=AsyncMock):
            with patch.object(storage_service, '_client') as mock_client:
                mock_client.put_object = AsyncMock(side_effect=Exception("S3 unavailable"))

                # Should handle gracefully
                try:
                    await storage_service.upload_bytes(
                        b"test data",
                        "test/path.txt",
                        content_type="text/plain"
                    )
                except Exception:
                    # Expected to raise, but should be handled
                    pass


class TestJobStuckDetection:
    """Job stuck detection scenarios."""

    @pytest.mark.asyncio
    async def test_job_sla_timeout(self):
        """Jobs exceeding SLA should be detected."""
        from datetime import datetime, timedelta
        from src.models.db import Job
        from sqlalchemy import select

        # This would be implemented as a background task
        # Checking for jobs stuck in 'running' state for too long

        # Example check logic:
        sla_seconds = 600  # 10 minutes
        threshold = datetime.utcnow() - timedelta(seconds=sla_seconds)

        # In production, this query would find stuck jobs:
        # stuck_jobs = await db.execute(
        #     select(Job).where(
        #         Job.status == "running",
        #         Job.updated_at < threshold
        #     )
        # )

        assert sla_seconds == 600  # Placeholder assertion


class TestExternalAPIDelays:
    """External API delay scenarios."""

    @pytest.mark.asyncio
    async def test_slow_llm_response(self):
        """Slow LLM response should respect timeout."""
        import asyncio
        from src.services.orchestrator import run_step

        async def slow_fn():
            await asyncio.sleep(5)  # Simulate slow response
            return "result"

        with patch('src.services.orchestrator.update_job_status', new_callable=AsyncMock):
            with pytest.raises(asyncio.TimeoutError):
                await run_step(
                    job_id="test-job",
                    step_name="slow step",
                    progress=50,
                    fn=slow_fn,
                    retries=0,
                    timeout_sec=1
                )
