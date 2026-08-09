#!/usr/bin/env python3
"""라이브 E2E 여정 드라이버 — 실행 중인 API 서버 대상.

단위테스트(in-process·TESTING=true)가 놓치는 *통합* 동작을 실제 HTTP로 검증한다:
프로필(DOB→연령대 파생) → 동의 → 책 생성 → 폴링 done(실제 오케스트레이터+mock providers)
→ 읽기/퀴즈 기록 → 성장 리포트 → 또래 비교 → 무료 오디오 게이트 → 스트릭 → 동의 철회
→ IDOR(타 유저 차단).

오프라인 구동(키·외부서비스 불필요):
  TESTING=false USE_CELERY=false LLM_PROVIDER=mock IMAGE_PROVIDER=mock TTS_PROVIDER=mock \
  DATABASE_URL=sqlite+aiosqlite:///./e2e.db (+ S3_* 더미) 로 uvicorn 구동 후 실행.

사용: python scripts/e2e_journey.py [BASE_URL]   (기본 http://127.0.0.1:8000)
종료코드 0=전부 통과, 1=실패.
"""

import os
import sys
import time
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
A = str(uuid.uuid4())  # 유저 A
B = str(uuid.uuid4())  # 유저 B(IDOR 검증용)

_passed = 0
_failed = 0


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ✅ {name}")
    else:
        _failed += 1
        print(f"  ❌ {name}  {detail}")


def h(user):
    return {"X-User-Key": user}


def main():
    print(f"== E2E 여정 (BASE={BASE}) ==")
    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        # 0. 헬스
        r = c.get("/health/live")
        check("health/live 200", r.status_code == 200, r.text[:120])

        # 1. 프로필 생성 — 생년월 → 연령대 자동 파생(부모가 보낸 age_band 무시)
        r = c.post(
            "/v1/profiles",
            headers=h(A),
            json={"name": "민지", "age_band": "3-5", "birth_year": 2019, "birth_month": 3},
        )
        check("프로필 생성 200", r.status_code == 200, r.text[:160])
        prof = r.json() if r.status_code == 200 else {}
        check("DOB→age_band 파생(2019-03생→7-9)", prof.get("age_band") == "7-9",
              f"got {prof.get('age_band')}")
        profile_id = prof.get("id")

        # 2. 보호자 동의 grant
        r = c.post("/v1/consent", headers=h(A),
                   json={"privacy": True, "photos": True, "data_processing": True})
        check("동의 grant 200", r.status_code == 200, r.text[:160])
        r = c.get("/v1/consent", headers=h(A))
        check("동의 조회 photos=true", r.status_code == 200 and r.json().get("photos") is True,
              r.text[:160])

        # 3. 책 생성(무료 플랜: watercolor, 3-5) — 신규 유저 기본 3크레딧
        r = c.post(
            "/v1/books",
            headers=h(A),
            json={"topic": "용감한 토끼의 모험", "language": "ko",
                  "target_age": "3-5", "style": "watercolor", "page_count": 8},
        )
        check("책 생성 요청 200", r.status_code == 200, r.text[:200])
        job_id = r.json().get("job_id") if r.status_code == 200 else None
        check("job_id 발급", bool(job_id), str(r.json())[:160] if r.status_code == 200 else "")

        # 4. done까지 폴링(실제 파이프라인 — mock이라 수초)
        book_id = None
        status = None
        if job_id:
            deadline = time.time() + 60
            while time.time() < deadline:
                rs = c.get(f"/v1/books/{job_id}", headers=h(A))
                if rs.status_code != 200:
                    break
                body = rs.json()
                status = body.get("status")
                if status in ("done", "failed"):
                    if status == "done" and body.get("result"):
                        book_id = body["result"].get("book_id")
                    break
                time.sleep(1.5)
        check("책 생성 done 도달", status == "done", f"최종 status={status}")
        check("결과 book_id 존재", bool(book_id), "")
        # 결과 페이지/이미지 검증
        if book_id:
            rs = c.get(f"/v1/books/{job_id}", headers=h(A)).json()
            pages = (rs.get("result") or {}).get("pages") or []
            cover = (rs.get("result") or {}).get("cover_image_url") or ""
            check("페이지 4+개 생성", len(pages) >= 4, f"pages={len(pages)}")
            check("커버 이미지 URL", cover.startswith("http"), cover[:60])

        # 4-1. 페이지 재생성 — **잡 완주 + 텍스트 실제 변경**까지 확인한다(S1).
        # 함정: 이 엔드포인트는 잡 등록만 하고 200 을 돌려준다. 200 만 보고 PASS 로 기록해
        # 매트릭스 #12/#22 가 두 라운드 연속 false-pass 였다(mock 이 RewriteResult 대신
        # StoryDraft 모양을 반환해 백그라운드 잡이 조용히 실패하고 있었다).
        if book_id and job_id:
            before = c.get(f"/v1/books/{book_id}/detail", headers=h(A)).json()
            before_text = next(
                (p["text"] for p in (before.get("pages") or []) if p["page_number"] == 2),
                None,
            )
            rr = c.post(
                f"/v1/books/{job_id}/pages/2/regenerate",
                headers=h(A),
                json={"mode": "text", "feedback": "더 밝게"},
            )
            check("페이지 재생성 요청 200", rr.status_code == 200, rr.text[:200])
            regen_job_id = rr.json().get("regen_job_id") or rr.json().get("job_id")

            regen_status = None
            regen_error = None
            if regen_job_id:
                deadline = time.time() + 60
                while time.time() < deadline:
                    rs = c.get(f"/v1/books/{regen_job_id}", headers=h(A))
                    if rs.status_code != 200:
                        break
                    body = rs.json()
                    regen_status = body.get("status")
                    if regen_status in ("done", "failed"):
                        regen_error = body.get("error")
                        break
                    time.sleep(1.0)
            check(
                "페이지 재생성 잡 done 도달",
                regen_status == "done",
                f"status={regen_status} error={regen_error}",
            )

            after = c.get(f"/v1/books/{book_id}/detail", headers=h(A)).json()
            after_text = next(
                (p["text"] for p in (after.get("pages") or []) if p["page_number"] == 2),
                None,
            )
            check(
                "재생성으로 페이지 텍스트가 실제로 변경됨",
                bool(after_text) and after_text != before_text,
                f"before={str(before_text)[:40]!r} after={str(after_text)[:40]!r}",
            )

        # 5. 읽기 기록(완독)
        rid = book_id or "fallback-book"
        r = c.post("/v1/streak/read", headers=h(A),
                   json={"book_id": rid, "reading_time": 120, "completed": True})
        check("읽기 기록(완독) 200", r.status_code == 200, r.text[:160])

        # 6. 퀴즈·어휘 응답 기록
        for qa in ({"book_id": rid, "quiz_type": "comprehension", "correct": True},
                   {"book_id": rid, "quiz_type": "vocab", "correct": True, "term": "용감"},
                   {"book_id": rid, "quiz_type": "vocab", "correct": True, "term": "토끼"}):
            r = c.post("/v1/growth/answers", headers=h(A), json=qa)
            check(f"응답 기록 {qa['quiz_type']} 200", r.status_code == 200, r.text[:120])

        # 7. 성장 리포트
        r = c.get("/v1/growth", headers=h(A))
        g = r.json() if r.status_code == 200 else {}
        check("성장 리포트 200", r.status_code == 200, r.text[:160])
        check("books_read>=1", g.get("books_read", 0) >= 1, str(g.get("books_read")))
        check("vocab_learned>=2", g.get("vocab_learned", 0) >= 2, str(g.get("vocab_learned")))
        check("reading_level 존재", isinstance(g.get("reading_level"), dict), "")
        check("completion 변별(0~1)", 0.0 <= g.get("completion", -1) <= 1.0, str(g.get("completion")))

        # 8. 또래 비교(또래 부족 → baseline·등수 미노출)
        r = c.get("/v1/growth/peers", headers=h(A))
        p = r.json() if r.status_code == 200 else {}
        check("또래 비교 200", r.status_code == 200, r.text[:160])
        check("baseline(또래<5)", p.get("is_baseline") is True, str(p.get("peer_count")))
        check("baseline 등수 미노출(show_ranking=False)", p.get("show_ranking") is False,
              str(p.get("show_ranking")))

        # 9. 오디오 게이트 — 기대 코드는 오디오 기능 플래그에 따라 갈린다.
        #   · 비활성(H1/G9 GA 기본): 라우터가 크레딧 체크 '전에' 409 AUDIO_NOT_SUPPORTED로 차단.
        #   · 활성: 무료 플랜 크레딧 게이트가 402로 차단.
        # 둘 다 '무료 사용자가 오디오를 받지 못한다'는 같은 계약이므로 플래그로 분기한다.
        r = c.post("/v1/books", headers=h(A),
                   json={"topic": "도서관의 비밀", "language": "ko",
                         "target_age": "5-7", "style": "watercolor", "page_count": 8})
        if r.status_code == 200:
            jid2 = r.json().get("job_id")
            deadline = time.time() + 60
            bid2 = None
            while time.time() < deadline:
                rs = c.get(f"/v1/books/{jid2}", headers=h(A)).json()
                if rs.get("status") in ("done", "failed"):
                    bid2 = (rs.get("result") or {}).get("book_id")
                    break
                time.sleep(1.5)
            if bid2:
                ra = c.get(f"/v1/books/{bid2}/pages/1/audio",
                           headers=h(A), params={"language": "ko"})
                audio_on = os.getenv("AUDIO_FEATURE_ENABLED", "false").strip().lower() in (
                    "1", "true", "yes", "on"
                )
                expected = 402 if audio_on else 409
                label = (
                    "무료 5-7 오디오 차단(402, 오디오 활성)"
                    if audio_on
                    else "오디오 비활성 차단(409 AUDIO_NOT_SUPPORTED)"
                )
                ok = ra.status_code == expected
                if not audio_on and ok:
                    # 코드뿐 아니라 사유까지 확인 — 다른 의미의 409를 통과로 세지 않는다.
                    body = ra.json() if ra.headers.get("content-type", "").startswith(
                        "application/json"
                    ) else {}
                    ok = (body.get("error") or {}).get("code") == "AUDIO_NOT_SUPPORTED"
                check(label, ok, f"got {ra.status_code}: {ra.text[:120]}")
        else:
            check("두번째 책 생성(오디오 게이트용)", False, r.text[:120])

        # 10. 스트릭
        r = c.get("/v1/streak/info", headers=h(A))
        s = r.json() if r.status_code == 200 else {}
        check("스트릭 조회 200", r.status_code == 200, r.text[:120])
        check("current_streak>=1", s.get("current_streak", 0) >= 1, str(s.get("current_streak")))

        # 11. IDOR — B가 A의 책으로 성장지표 기록 시도 → 403
        if book_id:
            r = c.post("/v1/growth/answers", headers=h(B),
                       json={"book_id": book_id, "quiz_type": "comprehension", "correct": True})
            check("IDOR: 타 유저 책 기록 차단(403)", r.status_code == 403, f"got {r.status_code}")
        # B가 A의 job 조회 → 403/404
        if job_id:
            r = c.get(f"/v1/books/{job_id}", headers=h(B))
            check("IDOR: 타 유저 job 조회 차단", r.status_code in (403, 404), f"got {r.status_code}")
        # B가 A의 프로필 삭제 시도 → 404(소유 아님)
        if profile_id:
            r = c.delete(f"/v1/profiles/{profile_id}", headers=h(B))
            check("IDOR: 타 유저 프로필 삭제 차단", r.status_code in (403, 404), f"got {r.status_code}")

        # 12. 동의 철회
        r = c.post("/v1/consent/revoke", headers=h(A))
        check("동의 철회 200", r.status_code == 200, r.text[:120])

    print(f"\n== 결과: {_passed} 통과 / {_failed} 실패 ==")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
