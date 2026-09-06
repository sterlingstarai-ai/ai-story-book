# 앱 내부 콘텐츠 신고

뷰어의 더보기 → **문제 신고**에서 보호자 확인 후 현재 표지 또는 본문 쪽과 사유를 전송한다. 앱 밖으로 이동하거나 이름·이메일·연락처·자유 입력을 추가 수집하지 않는다. 접수는 자동 수정·환불을 약속하지 않으며 운영 검토 대상으로 저장된다.

`POST /v1/books/{book_id}/reports`는 인증된 계정 및 선택 프로필의 책만 허용한다. 표지는 0, 본문은 실제 존재하는 쪽 번호이며 요청 전체에 기존 Redis 요청 제한을 적용한다. 같은 내용 버전·쪽·사유의 재전송은 기존 접수를 반환한다. 신고에는 원문·사진·프롬프트를 복사하지 않고 책 참조, 쪽, 사유, 내용 해시, 처리 상태와 시간만 저장한다. 책·계정 삭제와 사진 동의 철회에 따른 책 삭제 시 신고도 삭제한다.

## 운영 검토

배포 시 `alembic upgrade head`로 `d5e6f7a8b9c0`까지 적용한다. 아래 명령은 해당 환경의 DB 접근 권한을 가진 운영자만 실행한다. API의 Python 환경을 사용하며 환경 설정은 API의 `.env` 또는 명시적인 배포 환경을 따른다. 운영 DB 주소나 키를 명령행에 붙이지 않는다.

```bash
apps/api/venv/bin/python scripts/content_reports.py list
apps/api/venv/bin/python scripts/content_reports.py list --status in_review
apps/api/venv/bin/python scripts/content_reports.py export REPORT_ID --output /private/review/report.json
apps/api/venv/bin/python scripts/content_reports.py update REPORT_ID --status in_review
apps/api/venv/bin/python scripts/content_reports.py update REPORT_ID --status resolved --resolution content_corrected
apps/api/venv/bin/python scripts/content_reports.py update REPORT_ID --status dismissed --resolution no_violation
```

1. 베타 운영 중 접수 대기 및 검토 중 목록을 매일 확인한다. 목록은 아이 이름·본문·이미지 URL을 출력하지 않는다. 이 기능은 알림 발송 시스템을 포함하지 않으므로 담당자가 직접 확인해야 한다.
2. 필요할 때만 `export`로 한 건의 **현재** 본문과 이미지 주소를 새 0600 파일에 저장한다. 기존 파일은 덮어쓰지 않는다. 저장 위치는 Git·공유·클라우드 동기화 대상에서 제외하고 검토 후 삭제한다. `current_content_changed`가 참이면 신고 당시 버전과 현재 책이 달라졌다는 뜻이다. 신고 시점 원본 사본은 보관하지 않는다.
3. 사유와 실제 내용을 검토하고, 유해 생성이 확인되면 기존 소유권을 지키는 책 수정·삭제 흐름으로 조치한다. 재발 원인은 생성/검사 프롬프트와 회귀 샘플에 개인정보를 제거해 반영한다. 필요하면 신규 생성을 중지하고 수정한 뒤 재개한다.
4. `update`는 검토 결과만 기록하며 콘텐츠를 자동 수정하거나 삭제하지 않는다. 조치 후 `resolved`와 `content_corrected`/`content_removed`, 문제 없음·중복이면 `dismissed`와 `no_violation`/`duplicate`를 사용한다. 책이 삭제되면 신고도 없어지므로 별도 원문 사본을 남기지 않는다.

코드·모의 API/위젯 검증은 실제 운영자의 처리, 실기기 테스트, Google/Apple 심사 승인을 대신하지 않는다.

## 구현 검증 (2026-09-06)

- Python 3.12: 신고·OpenAPI 계약 23개 통과, 기존 삭제/FK·동의 철회 의미 회귀 18개 통과. 신규 마이그레이션을 임시 SQLite에 적용해 컬럼·고유 제약·삭제 CASCADE·되돌리기를 확인했다. PostgreSQL 실검증 결과로 간주하지 않는다.
- Flutter: 신고 위젯·HTTP 5개와 뷰어/기능 게이트 6개 통과. 보호자 확인 취소, 중복 전송 방지, 서버 오류 후 재시도, 320×480·글자 1.4배에서 스크롤과 최종 동작 접근을 확인했다. 정적 분석 무이슈.
- 실제 CLI 프로세스로 임시 합성 SQLite의 목록 조회·0600 파일 저장·처리 상태 변경을 확인했고 임시 DB와 파일을 제거했다. 운영 DB·유료 AI·스토어를 호출하지 않았다.
