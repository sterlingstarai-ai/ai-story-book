#!/usr/bin/env python3
"""
Load Test Script for AI Story Book

Generates N jobs and monitors their processing.
Collects metrics: processing time, failure rate, retry counts.
Calculates cost estimates based on actual API calls.

Usage:
    python scripts/load_test.py --jobs 100 --duration 3h --output results/
    python scripts/load_test.py --jobs 50 --concurrency 5 --mock
"""

import argparse
import asyncio
import json
import random
import time
import os
import sys
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path
import uuid

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "api"))


# ==================== Configuration ====================

TOPICS = [
    "숲속의 작은 토끼",
    "용감한 강아지 모험",
    "마법의 정원",
    "바다 탐험대",
    "하늘을 나는 고양이",
    "달나라 여행",
    "친구를 찾아서",
    "비밀의 숲",
    "무지개 나라",
    "꿈꾸는 아이",
    "작은 영웅의 이야기",
    "사계절 친구들",
    "별빛 마을",
    "동물 운동회",
    "요정과 곰돌이",
]

TARGET_AGES = ["3-5", "5-7", "7-9"]
STYLES = ["watercolor", "cartoon", "3d"]


@dataclass
class JobResult:
    job_id: str
    topic: str
    status: str
    start_time: float
    end_time: Optional[float] = None
    duration_seconds: Optional[float] = None
    retry_count: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    llm_calls: int = 0
    image_calls: int = 0
    progress_history: list = field(default_factory=list)


@dataclass
class LoadTestMetrics:
    test_id: str
    start_time: str
    end_time: Optional[str] = None
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    stuck_jobs: int = 0
    avg_duration_seconds: float = 0
    min_duration_seconds: float = 0
    max_duration_seconds: float = 0
    p50_duration_seconds: float = 0
    p95_duration_seconds: float = 0
    p99_duration_seconds: float = 0
    total_retries: int = 0
    avg_retries: float = 0
    total_llm_calls: int = 0
    total_image_calls: int = 0
    estimated_llm_cost: float = 0
    estimated_image_cost: float = 0
    estimated_total_cost: float = 0
    success_rate: float = 0
    jobs: list = field(default_factory=list)

    def calculate_stats(self, results: list[JobResult]):
        """Calculate statistics from job results"""
        self.total_jobs = len(results)
        self.completed_jobs = sum(1 for r in results if r.status == "done")
        self.failed_jobs = sum(1 for r in results if r.status == "failed")
        self.stuck_jobs = sum(1 for r in results if r.status in ["running", "queued"])

        completed = [r for r in results if r.status == "done" and r.duration_seconds]
        if completed:
            durations = sorted([r.duration_seconds for r in completed])
            self.avg_duration_seconds = sum(durations) / len(durations)
            self.min_duration_seconds = min(durations)
            self.max_duration_seconds = max(durations)
            self.p50_duration_seconds = durations[len(durations) // 2]
            self.p95_duration_seconds = durations[int(len(durations) * 0.95)]
            self.p99_duration_seconds = durations[int(len(durations) * 0.99)]

        self.total_retries = sum(r.retry_count for r in results)
        self.avg_retries = self.total_retries / len(results) if results else 0

        self.total_llm_calls = sum(r.llm_calls for r in results)
        self.total_image_calls = sum(r.image_calls for r in results)

        # Cost estimates
        # LLM: ~6000 tokens per book at $0.00015/1K tokens
        self.estimated_llm_cost = self.total_llm_calls * 0.0009
        # Images: ~$0.024 per image, 9 images per book
        self.estimated_image_cost = self.total_image_calls * 0.024

        self.estimated_total_cost = self.estimated_llm_cost + self.estimated_image_cost

        self.success_rate = (self.completed_jobs / self.total_jobs * 100) if self.total_jobs else 0

        self.jobs = [asdict(r) for r in results]


# ==================== Mock API Client ====================

class MockAPIClient:
    """Simulates API calls with realistic timing and failure rates"""

    def __init__(self, failure_rate: float = 0.05, slow_rate: float = 0.1):
        self.failure_rate = failure_rate
        self.slow_rate = slow_rate
        self.call_counts = {
            "llm": 0,
            "image": 0,
            "storage": 0,
        }

    async def create_job(self, topic: str, target_age: str, style: str) -> str:
        """Simulate job creation"""
        await asyncio.sleep(random.uniform(0.1, 0.3))
        job_id = f"job_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        return job_id

    async def poll_job_status(self, job_id: str) -> dict:
        """Simulate polling job status with realistic progress"""
        # Simulate different stages
        stage = random.choice(["queued", "running", "done", "failed"])
        progress = random.randint(0, 100)

        # Track calls
        if progress > 10:
            self.call_counts["llm"] += 1
        if progress > 55:
            self.call_counts["image"] += 1

        return {
            "job_id": job_id,
            "status": stage,
            "progress": progress,
            "current_step": "처리 중...",
        }


# ==================== Real API Client ====================

class RealAPIClient:
    """Real API client for actual testing"""

    def __init__(self, base_url: str, user_key: str):
        self.base_url = base_url.rstrip("/")
        self.user_key = user_key
        self.session = None

    async def _ensure_session(self):
        if self.session is None:
            import aiohttp
            self.session = aiohttp.ClientSession(
                headers={"X-User-Key": self.user_key}
            )

    async def create_job(self, topic: str, target_age: str, style: str) -> str:
        """Create a real job via API"""
        await self._ensure_session()

        payload = {
            "topic": topic,
            "target_age": target_age,
            "style": style,
            "page_count": 8,
        }

        async with self.session.post(
            f"{self.base_url}/v1/books",
            json=payload,
            headers={"X-Idempotency-Key": str(uuid.uuid4())}
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data["job_id"]
            else:
                text = await resp.text()
                raise Exception(f"Failed to create job: {resp.status} - {text}")

    async def poll_job_status(self, job_id: str) -> dict:
        """Poll job status via API"""
        await self._ensure_session()

        async with self.session.get(f"{self.base_url}/v1/books/{job_id}") as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                raise Exception(f"Failed to get job status: {resp.status}")

    async def close(self):
        if self.session:
            await self.session.close()


# ==================== Database Client ====================

class DatabaseClient:
    """Direct database access for metrics collection"""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = None

    async def connect(self):
        from sqlalchemy.ext.asyncio import create_async_engine
        self.engine = create_async_engine(self.database_url)

    async def get_job_metrics(self, job_ids: list) -> list[dict]:
        """Get detailed metrics for jobs"""
        from sqlalchemy import text

        if not self.engine:
            await self.connect()

        async with self.engine.connect() as conn:
            result = await conn.execute(
                text("""
                    SELECT id, status, progress, current_step, error_code, error_message,
                           retry_count, created_at, updated_at
                    FROM jobs
                    WHERE id = ANY(:job_ids)
                """),
                {"job_ids": job_ids}
            )
            return [dict(row._mapping) for row in result.fetchall()]

    async def create_stuck_job(self, user_key: str) -> str:
        """Create an artificially stuck job for testing"""
        from sqlalchemy import text

        if not self.engine:
            await self.connect()

        job_id = f"stuck_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        async with self.engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO jobs (id, status, progress, current_step, user_key, created_at, updated_at)
                    VALUES (:id, 'running', 50, 'Intentionally stuck for testing', :user_key,
                            :created_at, :updated_at)
                """),
                {
                    "id": job_id,
                    "user_key": user_key,
                    "created_at": datetime.utcnow() - timedelta(minutes=20),
                    "updated_at": datetime.utcnow() - timedelta(minutes=20),
                }
            )
        return job_id

    async def check_stuck_job_recovered(self, job_id: str) -> dict:
        """Check if stuck job was recovered by job monitor"""
        from sqlalchemy import text

        if not self.engine:
            await self.connect()

        async with self.engine.connect() as conn:
            result = await conn.execute(
                text("SELECT status, error_code, retry_count FROM jobs WHERE id = :id"),
                {"id": job_id}
            )
            row = result.fetchone()
            if row:
                return {
                    "status": row[0],
                    "error_code": row[1],
                    "retry_count": row[2],
                    "recovered": row[0] in ["failed", "queued"],
                }
            return {"recovered": False, "error": "Job not found"}

    async def close(self):
        if self.engine:
            await self.engine.dispose()


# ==================== Load Test Runner ====================

class LoadTestRunner:
    """Main load test orchestrator"""

    def __init__(
        self,
        num_jobs: int,
        concurrency: int,
        api_client,
        db_client: Optional[DatabaseClient] = None,
        output_dir: str = "results",
    ):
        self.num_jobs = num_jobs
        self.concurrency = concurrency
        self.api_client = api_client
        self.db_client = db_client
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.test_id = f"loadtest_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        self.results: list[JobResult] = []
        self.metrics = LoadTestMetrics(
            test_id=self.test_id,
            start_time=datetime.utcnow().isoformat(),
            total_jobs=num_jobs,
        )

        # Call tracking
        self.llm_calls = 0
        self.image_calls = 0

    async def run_single_job(self, job_num: int) -> JobResult:
        """Run a single job and collect metrics"""
        topic = random.choice(TOPICS)
        target_age = random.choice(TARGET_AGES)
        style = random.choice(STYLES)

        result = JobResult(
            job_id="",
            topic=topic,
            status="pending",
            start_time=time.time(),
        )

        try:
            # Create job
            job_id = await self.api_client.create_job(topic, target_age, style)
            result.job_id = job_id
            result.status = "queued"

            print(f"[{job_num}/{self.num_jobs}] Created job: {job_id} - {topic}")

            # Poll until completion (with timeout)
            timeout = 600  # 10 minutes
            poll_interval = 5
            elapsed = 0

            while elapsed < timeout:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                try:
                    status = await self.api_client.poll_job_status(job_id)
                    result.status = status.get("status", "unknown")
                    result.progress_history.append({
                        "time": time.time() - result.start_time,
                        "progress": status.get("progress", 0),
                        "step": status.get("current_step", ""),
                    })

                    # Track API calls based on progress
                    progress = status.get("progress", 0)
                    if progress > 10 and result.llm_calls == 0:
                        result.llm_calls = 1  # Moderation
                    if progress > 30 and result.llm_calls < 2:
                        result.llm_calls = 2  # Story generation
                    if progress > 40 and result.llm_calls < 3:
                        result.llm_calls = 3  # Character sheet
                    if progress > 55 and result.llm_calls < 4:
                        result.llm_calls = 4  # Image prompts
                    if progress > 55:
                        # Estimate image calls based on progress
                        images_progress = (progress - 55) / 40  # 55-95 is image generation
                        result.image_calls = min(9, int(images_progress * 9) + 1)

                    if result.status in ["done", "failed"]:
                        if result.status == "failed":
                            result.error_code = status.get("error", {}).get("code", "UNKNOWN")
                            result.error_message = status.get("error", {}).get("message", "")
                        break

                except Exception as e:
                    print(f"  Poll error: {e}")

            result.end_time = time.time()
            result.duration_seconds = result.end_time - result.start_time

            # Get retry count from DB if available
            if self.db_client:
                try:
                    metrics = await self.db_client.get_job_metrics([job_id])
                    if metrics:
                        result.retry_count = metrics[0].get("retry_count", 0)
                except Exception as e:
                    print(f"  DB metrics error: {e}")

            status_emoji = "✅" if result.status == "done" else "❌"
            print(f"[{job_num}/{self.num_jobs}] {status_emoji} {job_id}: {result.status} in {result.duration_seconds:.1f}s")

        except Exception as e:
            result.status = "error"
            result.error_message = str(e)
            result.end_time = time.time()
            result.duration_seconds = result.end_time - result.start_time
            print(f"[{job_num}/{self.num_jobs}] ❌ Error: {e}")

        return result

    async def run_concurrent_batch(self, job_nums: list[int]) -> list[JobResult]:
        """Run a batch of jobs concurrently"""
        tasks = [self.run_single_job(num) for num in job_nums]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self):
        """Run the full load test"""
        print(f"\n{'=' * 60}")
        print(f"Load Test Started: {self.test_id}")
        print(f"Jobs: {self.num_jobs}, Concurrency: {self.concurrency}")
        print(f"{'=' * 60}\n")

        # Run jobs in batches
        all_job_nums = list(range(1, self.num_jobs + 1))
        batches = [
            all_job_nums[i:i + self.concurrency]
            for i in range(0, len(all_job_nums), self.concurrency)
        ]

        for batch_num, batch in enumerate(batches, 1):
            print(f"\n--- Batch {batch_num}/{len(batches)} ---")
            batch_results = await self.run_concurrent_batch(batch)

            for r in batch_results:
                if isinstance(r, JobResult):
                    self.results.append(r)
                else:
                    # Handle exceptions
                    print(f"Batch error: {r}")

            # Save intermediate results
            self._save_intermediate_results()

            # Add delay between batches to avoid rate limiting
            if batch_num < len(batches):
                await asyncio.sleep(2)

        # Calculate final metrics
        self.metrics.end_time = datetime.utcnow().isoformat()
        self.metrics.calculate_stats(self.results)

        # Save final results
        self._save_final_results()

        return self.metrics

    async def test_stuck_job_recovery(self, user_key: str):
        """Test stuck job detection and recovery"""
        if not self.db_client:
            print("Skipping stuck job test - no database connection")
            return None

        print(f"\n{'=' * 60}")
        print("Testing Stuck Job Recovery")
        print(f"{'=' * 60}\n")

        # Create stuck jobs
        stuck_job_ids = []
        for i in range(3):
            job_id = await self.db_client.create_stuck_job(user_key)
            stuck_job_ids.append(job_id)
            print(f"Created stuck job: {job_id}")

        # Wait for job monitor to detect and recover (should be ~5 minutes)
        print("\nWaiting for job monitor to detect stuck jobs (5-10 minutes)...")
        for minute in range(15):
            await asyncio.sleep(60)
            print(f"  Elapsed: {minute + 1} minutes")

            # Check recovery status
            all_recovered = True
            for job_id in stuck_job_ids:
                status = await self.db_client.check_stuck_job_recovered(job_id)
                if status.get("recovered"):
                    print(f"  ✅ {job_id}: RECOVERED (status={status['status']}, retry_count={status.get('retry_count', 0)})")
                else:
                    print(f"  ⏳ {job_id}: Still stuck")
                    all_recovered = False

            if all_recovered:
                print("\n✅ All stuck jobs recovered!")
                break

        return stuck_job_ids

    def _save_intermediate_results(self):
        """Save intermediate results"""
        results_file = self.output_dir / f"{self.test_id}_intermediate.json"
        with open(results_file, "w") as f:
            json.dump({
                "test_id": self.test_id,
                "timestamp": datetime.utcnow().isoformat(),
                "completed": len(self.results),
                "total": self.num_jobs,
                "results": [asdict(r) for r in self.results],
            }, f, indent=2, default=str)

    def _save_final_results(self):
        """Save final results"""
        results_file = self.output_dir / f"{self.test_id}_final.json"
        with open(results_file, "w") as f:
            json.dump(asdict(self.metrics), f, indent=2, default=str)
        print(f"\nResults saved to: {results_file}")

    def print_summary(self):
        """Print test summary"""
        m = self.metrics
        print(f"\n{'=' * 60}")
        print(f"Load Test Summary: {m.test_id}")
        print(f"{'=' * 60}")
        print(f"\nJob Statistics:")
        print(f"  Total Jobs:     {m.total_jobs}")
        print(f"  Completed:      {m.completed_jobs} ({m.success_rate:.1f}%)")
        print(f"  Failed:         {m.failed_jobs}")
        print(f"  Stuck:          {m.stuck_jobs}")
        print(f"\nDuration (seconds):")
        print(f"  Average:        {m.avg_duration_seconds:.1f}s")
        print(f"  Min:            {m.min_duration_seconds:.1f}s")
        print(f"  Max:            {m.max_duration_seconds:.1f}s")
        print(f"  P50:            {m.p50_duration_seconds:.1f}s")
        print(f"  P95:            {m.p95_duration_seconds:.1f}s")
        print(f"  P99:            {m.p99_duration_seconds:.1f}s")
        print(f"\nRetry Statistics:")
        print(f"  Total Retries:  {m.total_retries}")
        print(f"  Avg Retries:    {m.avg_retries:.2f}")
        print(f"\nAPI Calls:")
        print(f"  LLM Calls:      {m.total_llm_calls}")
        print(f"  Image Calls:    {m.total_image_calls}")
        print(f"\nEstimated Costs:")
        print(f"  LLM Cost:       ${m.estimated_llm_cost:.4f}")
        print(f"  Image Cost:     ${m.estimated_image_cost:.2f}")
        print(f"  Total Cost:     ${m.estimated_total_cost:.2f}")
        print(f"  Cost per Book:  ${m.estimated_total_cost / m.total_jobs:.4f}" if m.total_jobs else "  N/A")
        print(f"\n{'=' * 60}")


# ==================== Simulation Mode ====================

class SimulatedJob:
    """Simulates a realistic job execution"""

    def __init__(self, job_id: str, topic: str):
        self.job_id = job_id
        self.topic = topic
        self.status = "queued"
        self.progress = 0
        self.llm_calls = 0
        self.image_calls = 0
        self.start_time = time.time()

        # Randomize execution characteristics
        self.will_fail = random.random() < 0.05  # 5% failure rate
        self.will_be_slow = random.random() < 0.1  # 10% slow jobs
        self.base_duration = random.uniform(60, 180)  # 1-3 minutes base
        if self.will_be_slow:
            self.base_duration *= 2

    async def simulate_step(self):
        """Simulate one step of job execution"""
        if self.status == "done" or self.status == "failed":
            return

        self.status = "running"

        # Progress through stages
        if self.progress < 10:
            await asyncio.sleep(random.uniform(0.5, 2))
            self.progress = 10
            self.llm_calls = 1  # Moderation
        elif self.progress < 30:
            await asyncio.sleep(random.uniform(2, 5))
            self.progress = 30
            self.llm_calls = 2  # Story
        elif self.progress < 40:
            await asyncio.sleep(random.uniform(1, 3))
            self.progress = 40
            self.llm_calls = 3  # Character
        elif self.progress < 55:
            await asyncio.sleep(random.uniform(1, 3))
            self.progress = 55
            self.llm_calls = 4  # Image prompts
        elif self.progress < 95:
            # Image generation - longest phase
            await asyncio.sleep(random.uniform(3, 8))
            self.progress = min(95, self.progress + random.randint(5, 15))
            self.image_calls = min(9, self.image_calls + 1)
        else:
            await asyncio.sleep(random.uniform(0.5, 2))
            self.progress = 100

            if self.will_fail and random.random() < 0.5:
                self.status = "failed"
            else:
                self.status = "done"


class SimulationRunner:
    """Runs simulated load test for quick validation"""

    def __init__(self, num_jobs: int, output_dir: str = "results"):
        self.num_jobs = num_jobs
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.test_id = f"simulation_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        self.jobs: list[SimulatedJob] = []
        self.results: list[JobResult] = []

    async def run(self):
        """Run simulation"""
        print(f"\n{'=' * 60}")
        print(f"Simulation Started: {self.test_id}")
        print(f"Jobs: {self.num_jobs}")
        print(f"{'=' * 60}\n")

        # Create all jobs
        for i in range(self.num_jobs):
            job_id = f"sim_{i:04d}_{uuid.uuid4().hex[:8]}"
            topic = random.choice(TOPICS)
            job = SimulatedJob(job_id, topic)
            self.jobs.append(job)

        # Run simulation
        start_time = time.time()
        active_jobs = self.jobs.copy()

        while active_jobs:
            # Process all active jobs
            for job in active_jobs[:]:
                await job.simulate_step()

                if job.status in ["done", "failed"]:
                    result = JobResult(
                        job_id=job.job_id,
                        topic=job.topic,
                        status=job.status,
                        start_time=job.start_time,
                        end_time=time.time(),
                        duration_seconds=time.time() - job.start_time,
                        llm_calls=job.llm_calls,
                        image_calls=job.image_calls,
                    )
                    self.results.append(result)
                    active_jobs.remove(job)
                    status_emoji = "✅" if job.status == "done" else "❌"
                    print(f"{status_emoji} {job.job_id}: {job.status} in {result.duration_seconds:.1f}s")

            # Show progress
            completed = len(self.results)
            if completed % 10 == 0:
                elapsed = time.time() - start_time
                print(f"  Progress: {completed}/{self.num_jobs} ({elapsed:.0f}s elapsed)")

            await asyncio.sleep(0.1)

        # Calculate metrics
        metrics = LoadTestMetrics(
            test_id=self.test_id,
            start_time=datetime.fromtimestamp(start_time).isoformat(),
            end_time=datetime.utcnow().isoformat(),
            total_jobs=self.num_jobs,
        )
        metrics.calculate_stats(self.results)

        # Save results
        results_file = self.output_dir / f"{self.test_id}_results.json"
        with open(results_file, "w") as f:
            json.dump(asdict(metrics), f, indent=2, default=str)

        return metrics


# ==================== Main ====================

async def main():
    parser = argparse.ArgumentParser(description="Load Test for AI Story Book")
    parser.add_argument("--jobs", type=int, default=100, help="Number of jobs to create")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent jobs")
    parser.add_argument("--duration", type=str, default="1h", help="Maximum duration (e.g., 3h)")
    parser.add_argument("--output", type=str, default="results", help="Output directory")
    parser.add_argument("--mock", action="store_true", help="Use mock API (no real calls)")
    parser.add_argument("--simulate", action="store_true", help="Run fast simulation")
    parser.add_argument("--api-url", type=str, default="http://localhost:8000", help="API base URL")
    parser.add_argument("--user-key", type=str, default="loadtest-user-001", help="User key")
    parser.add_argument("--test-stuck", action="store_true", help="Test stuck job recovery")
    parser.add_argument("--db-url", type=str, help="Database URL for direct access")

    args = parser.parse_args()

    # Create output directory
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.simulate:
        # Fast simulation mode
        runner = SimulationRunner(args.jobs, str(output_dir))
        metrics = await runner.run()

        # Print summary
        print(f"\n{'=' * 60}")
        print(f"Simulation Summary")
        print(f"{'=' * 60}")
        print(f"Success Rate: {metrics.success_rate:.1f}%")
        print(f"Avg Duration: {metrics.avg_duration_seconds:.1f}s")
        print(f"Total LLM Calls: {metrics.total_llm_calls}")
        print(f"Total Image Calls: {metrics.total_image_calls}")
        print(f"Estimated Cost: ${metrics.estimated_total_cost:.2f}")
        return

    # Set up clients
    if args.mock:
        api_client = MockAPIClient()
        db_client = None
    else:
        api_client = RealAPIClient(args.api_url, args.user_key)
        db_client = DatabaseClient(args.db_url) if args.db_url else None

    try:
        runner = LoadTestRunner(
            num_jobs=args.jobs,
            concurrency=args.concurrency,
            api_client=api_client,
            db_client=db_client,
            output_dir=str(output_dir),
        )

        # Run load test
        metrics = await runner.run()

        # Test stuck job recovery if requested
        if args.test_stuck and db_client:
            await runner.test_stuck_job_recovery(args.user_key)

        # Print summary
        runner.print_summary()

    finally:
        if hasattr(api_client, 'close'):
            await api_client.close()
        if db_client:
            await db_client.close()


if __name__ == "__main__":
    asyncio.run(main())
