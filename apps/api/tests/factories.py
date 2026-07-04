"""테스트용 ORM 객체 팩토리.

SQLite FK 강제(conftest) 하에서 합성 활동 데이터(ReadingLog/QuizAnswer/PronunciationLog)가
참조할 실제 Book(과 그 NOT NULL FK인 Job)을 만든다.
"""

from src.models.db import Book, Job


def make_book_rows(specs):
    """(book_id, user_key) 목록 → Job+Book ORM 객체 리스트(중복 book_id 제거).

    add_all 에 자식 행과 함께 넘기면 SQLAlchemy가 의존성 순서(Job→Book→자식)로 INSERT 한다.
    """
    rows = []
    seen = set()
    for book_id, user_key in specs:
        if not book_id or book_id in seen:
            continue
        seen.add(book_id)
        job_id = f"job-{book_id}"
        rows.append(Job(id=job_id, status="done", user_key=user_key))
        rows.append(
            Book(
                id=book_id,
                job_id=job_id,
                title="t",
                language="ko",
                target_age="5-7",
                style="watercolor",
                user_key=user_key,
            )
        )
    return rows
