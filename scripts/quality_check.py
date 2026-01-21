#!/usr/bin/env python3
"""
Quality Check Script for AI Story Book

Validates story quality, character consistency, and content safety.

Usage:
    python quality_check.py --book-id <book_id>
    python quality_check.py --recent 10
    python quality_check.py --ci --threshold 0.85
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Optional
from collections import Counter


# ==================== Configuration ====================

FORBIDDEN_PATTERNS = [
    # Violence (Korean)
    "죽이", "살인", "폭력", "피흘", "때리", "찌르", "총", "칼",
    # Violence (English)
    "kill", "murder", "blood", "violence", "weapon", "gun", "knife",
    # Adult content
    "술", "담배", "마약", "섹스", "성인", "야한",
    "alcohol", "drug", "sex", "adult", "nude", "nsfw",
    # Scary content
    "귀신", "악마", "지옥", "저주", "좀비",
    "ghost", "demon", "hell", "curse", "zombie",
    # Discrimination
    "바보", "멍청", "장애인", "차별",
    "stupid", "idiot", "retard",
]

AGE_REQUIREMENTS = {
    "3-5": {"min_words_per_page": 10, "max_words_per_page": 30, "min_pages": 6, "max_pages": 12},
    "5-7": {"min_words_per_page": 20, "max_words_per_page": 50, "min_pages": 6, "max_pages": 12},
    "7-9": {"min_words_per_page": 30, "max_words_per_page": 70, "min_pages": 6, "max_pages": 12},
    "adult": {"min_words_per_page": 40, "max_words_per_page": 120, "min_pages": 6, "max_pages": 12},
}

CHARACTER_ATTRIBUTES = [
    "hair", "eye", "skin", "dress", "shirt", "pants", "shoes",
    "머리", "눈", "피부", "옷", "드레스", "바지", "신발",
]


# ==================== Data Classes ====================

@dataclass
class CheckResult:
    passed: bool
    score: float
    details: str
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)


@dataclass
class QualityReport:
    book_id: str
    score: float
    passed: bool
    checks: dict
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "book_id": self.book_id,
            "score": round(self.score, 3),
            "passed": self.passed,
            "checks": {
                name: {
                    "passed": check.passed,
                    "score": round(check.score, 3),
                    "details": check.details,
                }
                for name, check in self.checks.items()
            },
            "warnings": self.warnings,
            "errors": self.errors,
        }


# ==================== Quality Checks ====================

def check_forbidden_content(text: str) -> CheckResult:
    """Check for forbidden content in text"""
    text_lower = text.lower()
    found_patterns = []

    for pattern in FORBIDDEN_PATTERNS:
        if pattern.lower() in text_lower:
            found_patterns.append(pattern)

    if found_patterns:
        return CheckResult(
            passed=False,
            score=0.0,
            details=f"Found forbidden patterns: {', '.join(found_patterns)}",
            errors=[f"Forbidden content: {p}" for p in found_patterns],
        )

    return CheckResult(
        passed=True,
        score=1.0,
        details="No forbidden content detected",
    )


def check_text_length(pages: list, target_age: str) -> CheckResult:
    """Check if text length is appropriate for age group"""
    requirements = AGE_REQUIREMENTS.get(target_age, AGE_REQUIREMENTS["5-7"])

    word_counts = []
    issues = []

    for page in pages:
        text = page.get("text", "")
        # Count words (handles both Korean and English)
        words = len(re.findall(r'\w+', text))
        word_counts.append(words)

        if words < requirements["min_words_per_page"]:
            issues.append(f"Page {page.get('page_number')}: too short ({words} words)")
        elif words > requirements["max_words_per_page"]:
            issues.append(f"Page {page.get('page_number')}: too long ({words} words)")

    # Calculate score
    total_pages = len(pages)
    if total_pages < requirements["min_pages"]:
        issues.append(f"Too few pages: {total_pages}")
    elif total_pages > requirements["max_pages"]:
        issues.append(f"Too many pages: {total_pages}")

    score = 1.0 - (len(issues) / (total_pages + 1))
    score = max(0.0, min(1.0, score))

    return CheckResult(
        passed=len(issues) == 0,
        score=score,
        details=f"Avg words/page: {sum(word_counts)/len(word_counts):.1f}" if word_counts else "No pages",
        warnings=issues if issues else [],
    )


def check_repetition(pages: list) -> CheckResult:
    """Check for excessive repetition"""
    all_sentences = []

    for page in pages:
        text = page.get("text", "")
        # Split into sentences
        sentences = re.split(r'[.!?。！？]', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        all_sentences.extend(sentences)

    if not all_sentences:
        return CheckResult(
            passed=True,
            score=1.0,
            details="No sentences to check",
        )

    # Count repeated sentences
    sentence_counts = Counter(all_sentences)
    repeated = sum(1 for count in sentence_counts.values() if count > 1)
    repetition_ratio = repeated / len(all_sentences)

    passed = repetition_ratio <= 0.15
    score = 1.0 - min(repetition_ratio * 3, 1.0)  # Penalize repetition

    return CheckResult(
        passed=passed,
        score=score,
        details=f"Repetition ratio: {repetition_ratio:.2%}",
        warnings=[f"High repetition: {repetition_ratio:.2%}"] if not passed else [],
    )


def check_vocabulary_diversity(pages: list) -> CheckResult:
    """Check vocabulary diversity"""
    all_words = []

    for page in pages:
        text = page.get("text", "")
        words = re.findall(r'\w+', text.lower())
        all_words.extend(words)

    if not all_words:
        return CheckResult(
            passed=True,
            score=1.0,
            details="No words to check",
        )

    unique_words = set(all_words)
    diversity = len(unique_words) / len(all_words)

    passed = diversity >= 0.4
    score = min(diversity / 0.6, 1.0)  # Normalize to 0-1

    return CheckResult(
        passed=passed,
        score=score,
        details=f"Vocabulary diversity: {diversity:.2%} ({len(unique_words)} unique / {len(all_words)} total)",
        warnings=[f"Low vocabulary diversity: {diversity:.2%}"] if not passed else [],
    )


def check_character_consistency(image_prompts: list) -> CheckResult:
    """Check if character description is consistent across prompts"""
    if not image_prompts:
        return CheckResult(
            passed=True,
            score=1.0,
            details="No image prompts to check",
        )

    # Extract character-related keywords from each prompt
    attribute_counts = {attr: 0 for attr in CHARACTER_ATTRIBUTES}

    for prompt in image_prompts:
        prompt_lower = prompt.lower() if isinstance(prompt, str) else ""
        for attr in CHARACTER_ATTRIBUTES:
            if attr.lower() in prompt_lower:
                attribute_counts[attr] += 1

    # Check if attributes appear consistently
    total_prompts = len(image_prompts)
    consistent_attrs = sum(
        1 for count in attribute_counts.values()
        if count == 0 or count >= total_prompts * 0.8
    )

    consistency_ratio = consistent_attrs / len(CHARACTER_ATTRIBUTES)
    passed = consistency_ratio >= 0.7

    return CheckResult(
        passed=passed,
        score=consistency_ratio,
        details=f"Character consistency: {consistency_ratio:.2%}",
        warnings=[f"Inconsistent character attributes"] if not passed else [],
    )


# ==================== Main Quality Check ====================

def run_quality_check(book_data: dict) -> QualityReport:
    """Run all quality checks on a book"""
    book_id = book_data.get("book_id", "unknown")
    pages = book_data.get("pages", [])
    target_age = book_data.get("target_age", "5-7")
    title = book_data.get("title", "")

    # Collect all text for content check
    all_text = title + " " + " ".join(p.get("text", "") for p in pages)

    # Run checks
    checks = {}

    # 1. Forbidden content check
    checks["forbidden_content"] = check_forbidden_content(all_text)

    # 2. Text length check
    checks["text_length"] = check_text_length(pages, target_age)

    # 3. Repetition check
    checks["repetition"] = check_repetition(pages)

    # 4. Vocabulary diversity check
    checks["vocabulary_diversity"] = check_vocabulary_diversity(pages)

    # 5. Character consistency check
    image_prompts = [p.get("image_prompt", "") for p in pages if p.get("image_prompt")]
    checks["character_consistency"] = check_character_consistency(image_prompts)

    # Calculate overall score (weighted average)
    weights = {
        "forbidden_content": 0.3,
        "text_length": 0.2,
        "repetition": 0.15,
        "vocabulary_diversity": 0.15,
        "character_consistency": 0.2,
    }

    total_score = sum(
        checks[name].score * weights.get(name, 0.1)
        for name in checks
    )

    # Collect all warnings and errors
    all_warnings = []
    all_errors = []
    for check in checks.values():
        all_warnings.extend(check.warnings)
        all_errors.extend(check.errors)

    # Determine pass/fail
    critical_checks = ["forbidden_content"]
    critical_passed = all(checks[name].passed for name in critical_checks if name in checks)
    overall_passed = critical_passed and total_score >= 0.7

    return QualityReport(
        book_id=book_id,
        score=total_score,
        passed=overall_passed,
        checks=checks,
        warnings=all_warnings,
        errors=all_errors,
    )


# ==================== Database Helpers ====================

def get_book_from_db(book_id: str) -> Optional[dict]:
    """Fetch book data from database"""
    try:
        import os
        import asyncio
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        database_url = os.environ.get("DATABASE_URL", "")
        if not database_url:
            print("Warning: DATABASE_URL not set, using mock data")
            return None

        # Convert async URL to sync
        sync_url = database_url.replace("+asyncpg", "")
        engine = create_engine(sync_url)
        Session = sessionmaker(bind=engine)

        with Session() as session:
            # Get book
            book = session.execute(
                text("SELECT id, title, target_age FROM books WHERE id = :id"),
                {"id": book_id}
            ).fetchone()

            if not book:
                return None

            # Get pages
            pages = session.execute(
                text("""
                    SELECT page_number, text, image_prompt
                    FROM pages
                    WHERE book_id = :book_id
                    ORDER BY page_number
                """),
                {"book_id": book_id}
            ).fetchall()

            return {
                "book_id": book[0],
                "title": book[1],
                "target_age": book[2],
                "pages": [
                    {
                        "page_number": p[0],
                        "text": p[1],
                        "image_prompt": p[2],
                    }
                    for p in pages
                ],
            }

    except Exception as e:
        print(f"Database error: {e}")
        return None


def get_recent_books(limit: int) -> list:
    """Fetch recent books from database"""
    try:
        import os
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        database_url = os.environ.get("DATABASE_URL", "")
        if not database_url:
            return []

        sync_url = database_url.replace("+asyncpg", "")
        engine = create_engine(sync_url)
        Session = sessionmaker(bind=engine)

        with Session() as session:
            books = session.execute(
                text("""
                    SELECT id FROM books
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"limit": limit}
            ).fetchall()

            return [b[0] for b in books]

    except Exception as e:
        print(f"Database error: {e}")
        return []


# ==================== CLI ====================

def main():
    parser = argparse.ArgumentParser(description="Quality check for AI Story Book")
    parser.add_argument("--book-id", help="Specific book ID to check")
    parser.add_argument("--recent", type=int, help="Check N most recent books")
    parser.add_argument("--ci", action="store_true", help="CI mode (exit with error on failure)")
    parser.add_argument("--threshold", type=float, default=0.85, help="Pass threshold (default: 0.85)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--mock", action="store_true", help="Use mock data for testing")

    args = parser.parse_args()

    # Get books to check
    books_to_check = []

    if args.mock or (not args.book_id and not args.recent):
        # Use mock data for testing
        mock_book = {
            "book_id": "mock_book_001",
            "title": "숲속의 작은 친구들",
            "target_age": "3-5",
            "pages": [
                {"page_number": 1, "text": "숲속에 작은 토끼가 살았어요. 토끼는 당근을 좋아했어요.", "image_prompt": "cute rabbit with brown fur"},
                {"page_number": 2, "text": "어느 날 토끼는 새 친구를 만났어요. 다람쥐였어요.", "image_prompt": "rabbit meeting a squirrel"},
                {"page_number": 3, "text": "토끼와 다람쥐는 함께 놀았어요. 너무 재미있었어요.", "image_prompt": "rabbit and squirrel playing"},
                {"page_number": 4, "text": "해가 지고 집에 돌아갈 시간이었어요.", "image_prompt": "sunset in the forest"},
                {"page_number": 5, "text": "토끼는 내일 또 만나자고 약속했어요.", "image_prompt": "rabbit waving goodbye"},
                {"page_number": 6, "text": "다람쥐도 기쁘게 약속했어요.", "image_prompt": "squirrel smiling"},
                {"page_number": 7, "text": "토끼는 행복한 마음으로 집에 돌아갔어요.", "image_prompt": "rabbit going home happy"},
                {"page_number": 8, "text": "그날 밤 토끼는 새 친구 꿈을 꾸었어요. 끝.", "image_prompt": "rabbit sleeping peacefully"},
            ],
        }
        books_to_check.append(mock_book)

    elif args.book_id:
        book_data = get_book_from_db(args.book_id)
        if book_data:
            books_to_check.append(book_data)
        else:
            print(f"Book not found: {args.book_id}")
            sys.exit(1)

    elif args.recent:
        book_ids = get_recent_books(args.recent)
        for book_id in book_ids:
            book_data = get_book_from_db(book_id)
            if book_data:
                books_to_check.append(book_data)

    # Run quality checks
    results = []
    failed_count = 0

    for book_data in books_to_check:
        report = run_quality_check(book_data)
        results.append(report)

        if not report.passed or report.score < args.threshold:
            failed_count += 1

    # Output results
    if args.json:
        output = {
            "total": len(results),
            "passed": len(results) - failed_count,
            "failed": failed_count,
            "threshold": args.threshold,
            "results": [r.to_dict() for r in results],
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(f"\n{'=' * 60}")
        print(f"Quality Check Results")
        print(f"{'=' * 60}\n")

        for report in results:
            status = "✅ PASS" if report.passed and report.score >= args.threshold else "❌ FAIL"
            print(f"Book: {report.book_id}")
            print(f"Status: {status}")
            print(f"Score: {report.score:.2%}")
            print(f"\nChecks:")
            for name, check in report.checks.items():
                check_status = "✓" if check.passed else "✗"
                print(f"  {check_status} {name}: {check.score:.2%} - {check.details}")

            if report.warnings:
                print(f"\nWarnings:")
                for warning in report.warnings:
                    print(f"  ⚠️  {warning}")

            if report.errors:
                print(f"\nErrors:")
                for error in report.errors:
                    print(f"  ❌ {error}")

            print(f"\n{'-' * 60}\n")

        print(f"Summary: {len(results) - failed_count}/{len(results)} passed (threshold: {args.threshold:.0%})")

    # Exit with error in CI mode if any failed
    if args.ci and failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
