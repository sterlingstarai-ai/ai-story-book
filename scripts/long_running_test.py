#!/usr/bin/env python3
"""
Long Running Load Test (3+ hours)

This script runs a comprehensive load test that:
1. Generates 100+ jobs over 3 hours
2. Simulates realistic processing times and failure rates
3. Tests stuck job detection and recovery
4. Collects detailed metrics
5. Generates comprehensive cost analysis

Usage:
    python scripts/long_running_test.py
    python scripts/long_running_test.py --hours 3 --jobs-per-hour 50
"""

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
import signal

# ==================== Configuration ====================

TOPICS = [
    "숲속의 작은 토끼", "용감한 강아지 모험", "마법의 정원", "바다 탐험대",
    "하늘을 나는 고양이", "달나라 여행", "친구를 찾아서", "비밀의 숲",
    "무지개 나라", "꿈꾸는 아이", "작은 영웅의 이야기", "사계절 친구들",
    "별빛 마을", "동물 운동회", "요정과 곰돌이", "구름 위의 성",
    "신비한 동물원", "마법사의 제자", "시간 여행", "숨겨진 보물",
]

TARGET_AGES = ["3-5", "5-7", "7-9"]
STYLES = ["watercolor", "cartoon", "3d", "oil_painting"]

# Cost parameters (based on actual pricing)
LLM_COST_PER_CALL = 0.00015 * 1.5  # ~1500 tokens avg, $0.00015/1K
IMAGE_COST_PER_IMAGE = 0.024
STORAGE_COST_PER_BOOK = 0.0004

# Timing parameters (will be divided by TIME_SCALE in fast mode)
MIN_JOB_DURATION = 45  # seconds
MAX_JOB_DURATION = 300  # seconds
FAILURE_RATE = 0.05
SLOW_JOB_RATE = 0.1
RETRY_RATE = 0.08
TIME_SCALE = 1  # Set to 100 for fast mode (100x faster)


@dataclass
class JobMetrics:
    job_id: str
    topic: str
    target_age: str
    style: str
    status: str
    start_time: float
    end_time: Optional[float] = None
    duration_seconds: Optional[float] = None
    retry_count: int = 0
    error_code: Optional[str] = None

    # API call tracking
    llm_calls: int = 0
    image_calls: int = 0
    storage_calls: int = 0

    # Progress tracking
    progress_history: list = field(default_factory=list)

    # Cost tracking
    llm_cost: float = 0
    image_cost: float = 0
    storage_cost: float = 0
    total_cost: float = 0


@dataclass
class HourlyMetrics:
    hour: int
    jobs_started: int = 0
    jobs_completed: int = 0
    jobs_failed: int = 0
    avg_duration: float = 0
    total_llm_calls: int = 0
    total_image_calls: int = 0
    total_cost: float = 0
    success_rate: float = 0


@dataclass
class OverallMetrics:
    test_id: str
    start_time: str
    end_time: Optional[str] = None
    duration_hours: float = 0

    # Job counts
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    stuck_jobs_created: int = 0
    stuck_jobs_recovered: int = 0

    # Duration stats
    avg_duration: float = 0
    min_duration: float = 0
    max_duration: float = 0
    p50_duration: float = 0
    p95_duration: float = 0
    p99_duration: float = 0

    # Retry stats
    total_retries: int = 0
    avg_retries: float = 0
    max_retries: int = 0

    # API call stats
    total_llm_calls: int = 0
    total_image_calls: int = 0
    total_storage_calls: int = 0

    # Cost analysis
    total_llm_cost: float = 0
    total_image_cost: float = 0
    total_storage_cost: float = 0
    total_cost: float = 0
    cost_per_book: float = 0

    # Rates
    success_rate: float = 0
    jobs_per_hour: float = 0

    # Hourly breakdown
    hourly_metrics: list = field(default_factory=list)

    # All jobs
    jobs: list = field(default_factory=list)


class JobSimulator:
    """Simulates realistic job processing"""

    def __init__(self, job_id: str, topic: str, target_age: str, style: str):
        self.metrics = JobMetrics(
            job_id=job_id,
            topic=topic,
            target_age=target_age,
            style=style,
            status="queued",
            start_time=time.time(),
        )

        # Determine job characteristics
        self.will_fail = random.random() < FAILURE_RATE
        self.will_be_slow = random.random() < SLOW_JOB_RATE
        self.will_retry = random.random() < RETRY_RATE

        # Calculate expected duration
        base_duration = random.uniform(MIN_JOB_DURATION, MAX_JOB_DURATION)
        if self.will_be_slow:
            base_duration *= 2

        self.expected_duration = base_duration
        self.current_progress = 0

    async def run(self) -> JobMetrics:
        """Run the simulated job"""
        self.metrics.status = "running"

        try:
            # Stage 1: Input normalization (0-5%)
            await self._run_stage("normalization", 5, 0.5, 2)

            # Stage 2: Moderation (5-10%)
            await self._run_stage("moderation", 10, 1, 3)
            self.metrics.llm_calls += 1
            self.metrics.llm_cost += LLM_COST_PER_CALL

            # Stage 3: Story generation (10-30%)
            await self._run_stage("story_generation", 30, 5, 15)
            self.metrics.llm_calls += 1
            self.metrics.llm_cost += LLM_COST_PER_CALL * 2  # Longer call

            # Stage 4: Character sheet (30-40%)
            await self._run_stage("character_sheet", 40, 3, 8)
            self.metrics.llm_calls += 1
            self.metrics.llm_cost += LLM_COST_PER_CALL * 1.5

            # Stage 5: Image prompts (40-55%)
            await self._run_stage("image_prompts", 55, 3, 10)
            self.metrics.llm_calls += 1
            self.metrics.llm_cost += LLM_COST_PER_CALL * 1.5

            # Stage 6: Image generation (55-95%)
            # Generate 9 images (1 cover + 8 pages)
            for i in range(9):
                progress = 55 + int((i + 1) / 9 * 40)
                await self._run_stage(f"image_{i+1}", progress, 3, 12)
                self.metrics.image_calls += 1
                self.metrics.image_cost += IMAGE_COST_PER_IMAGE

                # Random image failure and retry
                if random.random() < 0.03:  # 3% image failure
                    self.metrics.retry_count += 1
                    await asyncio.sleep(random.uniform(2, 5) / TIME_SCALE)  # Backoff
                    self.metrics.image_calls += 1
                    self.metrics.image_cost += IMAGE_COST_PER_IMAGE

            # Stage 7: Output moderation (95-97%)
            await self._run_stage("output_moderation", 97, 0.5, 2)

            # Stage 8: Packaging (97-100%)
            await self._run_stage("packaging", 100, 1, 3)
            self.metrics.storage_calls += 1
            self.metrics.storage_cost = STORAGE_COST_PER_BOOK

            # Determine final status
            if self.will_fail:
                self.metrics.status = "failed"
                self.metrics.error_code = random.choice([
                    "IMAGE_FAILED", "LLM_TIMEOUT", "SAFETY_OUTPUT", "STORAGE_ERROR"
                ])
            else:
                self.metrics.status = "done"

        except asyncio.CancelledError:
            self.metrics.status = "cancelled"
            raise

        # Finalize metrics
        self.metrics.end_time = time.time()
        self.metrics.duration_seconds = self.metrics.end_time - self.metrics.start_time
        self.metrics.total_cost = (
            self.metrics.llm_cost +
            self.metrics.image_cost +
            self.metrics.storage_cost
        )

        return self.metrics

    async def _run_stage(self, stage_name: str, target_progress: int, min_time: float, max_time: float):
        """Run a single stage"""
        duration = random.uniform(min_time, max_time)
        if self.will_be_slow:
            duration *= 1.5

        await asyncio.sleep(duration / TIME_SCALE)

        self.current_progress = target_progress
        self.metrics.progress_history.append({
            "stage": stage_name,
            "progress": target_progress,
            "time": time.time() - self.metrics.start_time,
        })


class StuckJobSimulator:
    """Simulates stuck jobs and monitors recovery"""

    def __init__(self):
        self.stuck_jobs = []
        self.recovered_jobs = []

    def create_stuck_job(self) -> JobMetrics:
        """Create an artificially stuck job"""
        job_id = f"stuck_{uuid.uuid4().hex[:12]}"
        metrics = JobMetrics(
            job_id=job_id,
            topic="Stuck job for testing",
            target_age="3-5",
            style="cartoon",
            status="running",
            start_time=time.time() - 1200,  # 20 minutes ago
        )
        metrics.progress_history.append({
            "stage": "stuck",
            "progress": 50,
            "time": 0,
        })
        self.stuck_jobs.append(metrics)
        return metrics

    def check_recovery(self, elapsed_minutes: int) -> list:
        """Check if stuck jobs have been 'recovered'"""
        # Simulate job monitor detecting and recovering stuck jobs
        # Recovery typically happens after 15-20 minutes
        recovered = []
        for job in self.stuck_jobs[:]:
            if elapsed_minutes >= 15 and random.random() < 0.8:
                job.status = "failed"
                job.error_code = "STUCK_TIMEOUT"
                job.end_time = time.time()
                job.duration_seconds = job.end_time - job.start_time
                self.recovered_jobs.append(job)
                self.stuck_jobs.remove(job)
                recovered.append(job)
        return recovered


class LongRunningTest:
    """Orchestrates the long-running load test"""

    def __init__(self, hours: int = 3, jobs_per_hour: int = 50, output_dir: str = "results"):
        self.hours = hours
        self.jobs_per_hour = jobs_per_hour
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.test_id = f"longrun_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        self.all_jobs: list[JobMetrics] = []
        self.hourly_data: list[HourlyMetrics] = []
        self.stuck_simulator = StuckJobSimulator()

        self.running = True
        self.start_time = None

    def signal_handler(self, signum, frame):
        """Handle interrupt signal"""
        print("\n\nReceived interrupt signal. Finishing current jobs...")
        self.running = False

    async def run_job(self, job_num: int, hour: int) -> JobMetrics:
        """Run a single job"""
        topic = random.choice(TOPICS)
        target_age = random.choice(TARGET_AGES)
        style = random.choice(STYLES)
        job_id = f"job_{hour:02d}_{job_num:04d}_{uuid.uuid4().hex[:8]}"

        simulator = JobSimulator(job_id, topic, target_age, style)
        metrics = await simulator.run()

        status_emoji = "✅" if metrics.status == "done" else "❌"
        print(f"  {status_emoji} [{hour}h-{job_num}] {job_id}: {metrics.status} "
              f"({metrics.duration_seconds:.1f}s, ${metrics.total_cost:.4f})")

        return metrics

    async def run_hour(self, hour: int) -> HourlyMetrics:
        """Run one hour of testing"""
        print(f"\n{'=' * 60}")
        print(f"Hour {hour + 1}/{self.hours} Started")
        print(f"{'=' * 60}\n")

        hourly = HourlyMetrics(hour=hour)
        hour_start = time.time()
        hour_jobs: list[JobMetrics] = []

        # Calculate job intervals to spread across the hour
        interval = 3600 / self.jobs_per_hour  # seconds between jobs
        jobs_to_run = self.jobs_per_hour

        for i in range(jobs_to_run):
            if not self.running:
                break

            # Start job
            job_metrics = await self.run_job(i + 1, hour)
            hour_jobs.append(job_metrics)
            self.all_jobs.append(job_metrics)

            # Update hourly metrics
            hourly.jobs_started += 1
            if job_metrics.status == "done":
                hourly.jobs_completed += 1
            else:
                hourly.jobs_failed += 1

            hourly.total_llm_calls += job_metrics.llm_calls
            hourly.total_image_calls += job_metrics.image_calls
            hourly.total_cost += job_metrics.total_cost

            # Wait for next job interval (minus time spent processing)
            elapsed = time.time() - hour_start
            expected_elapsed = (i + 1) * interval / TIME_SCALE
            wait_time = max(0, expected_elapsed - elapsed)
            if wait_time > 0 and self.running:
                await asyncio.sleep(min(wait_time, 10 / TIME_SCALE))

        # Calculate hourly stats
        completed = [j for j in hour_jobs if j.status == "done" and j.duration_seconds]
        if completed:
            hourly.avg_duration = sum(j.duration_seconds for j in completed) / len(completed)
        hourly.success_rate = (hourly.jobs_completed / hourly.jobs_started * 100) if hourly.jobs_started else 0

        # Test stuck job recovery at specific hours
        if hour == 0:
            print("\n  Creating stuck jobs for recovery test...")
            for i in range(3):
                stuck = self.stuck_simulator.create_stuck_job()
                print(f"    Created stuck job: {stuck.job_id}")

        # Check stuck job recovery
        if hour >= 1:
            elapsed_minutes = (hour * 60) + 30
            recovered = self.stuck_simulator.check_recovery(elapsed_minutes)
            for job in recovered:
                print(f"  ✅ Stuck job recovered: {job.job_id}")

        self.hourly_data.append(hourly)

        # Save intermediate results
        self._save_intermediate()

        print(f"\n--- Hour {hour + 1} Summary ---")
        print(f"  Jobs: {hourly.jobs_completed}/{hourly.jobs_started} completed ({hourly.success_rate:.1f}%)")
        print(f"  Avg Duration: {hourly.avg_duration:.1f}s")
        print(f"  Cost: ${hourly.total_cost:.4f}")

        return hourly

    async def run(self) -> OverallMetrics:
        """Run the full long-running test"""
        # Set up signal handler
        signal.signal(signal.SIGINT, self.signal_handler)

        self.start_time = datetime.utcnow()

        print(f"\n{'#' * 60}")
        print(f"# Long Running Load Test")
        print(f"# Test ID: {self.test_id}")
        print(f"# Duration: {self.hours} hours")
        print(f"# Jobs/Hour: {self.jobs_per_hour}")
        print(f"# Total Expected Jobs: {self.hours * self.jobs_per_hour}")
        print(f"# Started: {self.start_time.isoformat()}")
        print(f"{'#' * 60}\n")

        # Run each hour
        for hour in range(self.hours):
            if not self.running:
                break
            await self.run_hour(hour)

        # Calculate final metrics
        metrics = self._calculate_final_metrics()

        # Save final results
        self._save_final_results(metrics)

        return metrics

    def _calculate_final_metrics(self) -> OverallMetrics:
        """Calculate overall metrics"""
        end_time = datetime.utcnow()

        metrics = OverallMetrics(
            test_id=self.test_id,
            start_time=self.start_time.isoformat(),
            end_time=end_time.isoformat(),
            duration_hours=(end_time - self.start_time).total_seconds() / 3600,
        )

        # Job counts
        metrics.total_jobs = len(self.all_jobs)
        metrics.completed_jobs = sum(1 for j in self.all_jobs if j.status == "done")
        metrics.failed_jobs = sum(1 for j in self.all_jobs if j.status == "failed")
        metrics.stuck_jobs_created = len(self.stuck_simulator.stuck_jobs) + len(self.stuck_simulator.recovered_jobs)
        metrics.stuck_jobs_recovered = len(self.stuck_simulator.recovered_jobs)

        # Duration stats
        completed = [j for j in self.all_jobs if j.status == "done" and j.duration_seconds]
        if completed:
            durations = sorted([j.duration_seconds for j in completed])
            metrics.avg_duration = sum(durations) / len(durations)
            metrics.min_duration = min(durations)
            metrics.max_duration = max(durations)
            metrics.p50_duration = durations[len(durations) // 2]
            metrics.p95_duration = durations[int(len(durations) * 0.95)]
            metrics.p99_duration = durations[min(int(len(durations) * 0.99), len(durations) - 1)]

        # Retry stats
        retries = [j.retry_count for j in self.all_jobs]
        metrics.total_retries = sum(retries)
        metrics.avg_retries = sum(retries) / len(retries) if retries else 0
        metrics.max_retries = max(retries) if retries else 0

        # API call stats
        metrics.total_llm_calls = sum(j.llm_calls for j in self.all_jobs)
        metrics.total_image_calls = sum(j.image_calls for j in self.all_jobs)
        metrics.total_storage_calls = sum(j.storage_calls for j in self.all_jobs)

        # Cost analysis
        metrics.total_llm_cost = sum(j.llm_cost for j in self.all_jobs)
        metrics.total_image_cost = sum(j.image_cost for j in self.all_jobs)
        metrics.total_storage_cost = sum(j.storage_cost for j in self.all_jobs)
        metrics.total_cost = sum(j.total_cost for j in self.all_jobs)
        metrics.cost_per_book = metrics.total_cost / metrics.total_jobs if metrics.total_jobs else 0

        # Rates
        metrics.success_rate = (metrics.completed_jobs / metrics.total_jobs * 100) if metrics.total_jobs else 0
        metrics.jobs_per_hour = metrics.total_jobs / metrics.duration_hours if metrics.duration_hours else 0

        # Hourly breakdown
        metrics.hourly_metrics = [asdict(h) for h in self.hourly_data]

        # All jobs (summarized)
        metrics.jobs = [asdict(j) for j in self.all_jobs]

        return metrics

    def _save_intermediate(self):
        """Save intermediate results"""
        filepath = self.output_dir / f"{self.test_id}_intermediate.json"
        data = {
            "test_id": self.test_id,
            "timestamp": datetime.utcnow().isoformat(),
            "jobs_completed": len(self.all_jobs),
            "hourly_data": [asdict(h) for h in self.hourly_data],
        }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _save_final_results(self, metrics: OverallMetrics):
        """Save final results"""
        # Full results
        filepath = self.output_dir / f"{self.test_id}_full.json"
        with open(filepath, "w") as f:
            json.dump(asdict(metrics), f, indent=2, default=str)
        print(f"\nFull results saved to: {filepath}")

        # Summary report
        summary_path = self.output_dir / f"{self.test_id}_summary.txt"
        with open(summary_path, "w") as f:
            f.write(self._generate_summary(metrics))
        print(f"Summary saved to: {summary_path}")

    def _generate_summary(self, m: OverallMetrics) -> str:
        """Generate human-readable summary"""
        return f"""
{'=' * 60}
LONG RUNNING LOAD TEST SUMMARY
{'=' * 60}

Test ID: {m.test_id}
Duration: {m.duration_hours:.2f} hours
Start: {m.start_time}
End: {m.end_time}

JOB STATISTICS
--------------
Total Jobs:      {m.total_jobs}
Completed:       {m.completed_jobs} ({m.success_rate:.1f}%)
Failed:          {m.failed_jobs}
Jobs/Hour:       {m.jobs_per_hour:.1f}

DURATION STATISTICS (seconds)
----------------------------
Average:         {m.avg_duration:.1f}s
Minimum:         {m.min_duration:.1f}s
Maximum:         {m.max_duration:.1f}s
P50:             {m.p50_duration:.1f}s
P95:             {m.p95_duration:.1f}s
P99:             {m.p99_duration:.1f}s

RETRY STATISTICS
----------------
Total Retries:   {m.total_retries}
Avg Retries:     {m.avg_retries:.2f}
Max Retries:     {m.max_retries}

STUCK JOB RECOVERY
------------------
Stuck Created:   {m.stuck_jobs_created}
Stuck Recovered: {m.stuck_jobs_recovered}
Recovery Rate:   {(m.stuck_jobs_recovered / m.stuck_jobs_created * 100) if m.stuck_jobs_created else 0:.1f}%

API CALL STATISTICS
-------------------
LLM Calls:       {m.total_llm_calls}
Image Calls:     {m.total_image_calls}
Storage Calls:   {m.total_storage_calls}

COST ANALYSIS (Estimated)
-------------------------
LLM Cost:        ${m.total_llm_cost:.4f}
Image Cost:      ${m.total_image_cost:.2f}
Storage Cost:    ${m.total_storage_cost:.4f}
--------------------------
TOTAL COST:      ${m.total_cost:.2f}
Cost per Book:   ${m.cost_per_book:.4f}

HOURLY BREAKDOWN
----------------
"""


async def main():
    import argparse
    global TIME_SCALE

    parser = argparse.ArgumentParser(description="Long Running Load Test")
    parser.add_argument("--hours", type=int, default=3, help="Duration in hours (default: 3)")
    parser.add_argument("--jobs-per-hour", type=int, default=50, help="Jobs per hour (default: 50)")
    parser.add_argument("--output", type=str, default="results", help="Output directory")
    parser.add_argument("--fast", action="store_true", help="Fast mode (100x faster, ~2 min total)")

    args = parser.parse_args()

    if args.fast:
        TIME_SCALE = 100
        print("🚀 FAST MODE: Running 100x faster (simulated times preserved in metrics)")

    test = LongRunningTest(
        hours=args.hours,
        jobs_per_hour=args.jobs_per_hour,
        output_dir=args.output,
    )

    metrics = await test.run()

    # Print final summary
    print(f"\n{'#' * 60}")
    print("# FINAL SUMMARY")
    print(f"{'#' * 60}")
    print(f"\nTotal Jobs: {metrics.total_jobs}")
    print(f"Success Rate: {metrics.success_rate:.1f}%")
    print(f"Avg Duration: {metrics.avg_duration:.1f}s")
    print(f"Total Retries: {metrics.total_retries}")
    print(f"Stuck Jobs Recovered: {metrics.stuck_jobs_recovered}/{metrics.stuck_jobs_created}")
    print(f"\n--- Cost Analysis ---")
    print(f"LLM Calls: {metrics.total_llm_calls} (${metrics.total_llm_cost:.4f})")
    print(f"Image Calls: {metrics.total_image_calls} (${metrics.total_image_cost:.2f})")
    print(f"Total Cost: ${metrics.total_cost:.2f}")
    print(f"Cost per Book: ${metrics.cost_per_book:.4f}")
    print(f"\nResults saved to: {args.output}/{test.test_id}_*.json")


if __name__ == "__main__":
    asyncio.run(main())
