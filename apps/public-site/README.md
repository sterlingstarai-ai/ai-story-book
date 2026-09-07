# 앱 지원·삭제 안내 페이지

별도 웹앱 가입이나 로그인 없이 읽는 정적 도움말이다. 문의와 삭제 요청은 검증된 운영 지원 이메일을 연결한다. 폼 서버·분석 도구·외부 폰트·쿠키·AI 호출은 없다. 기존 PIPA 동의문이나 개인정보처리방침 원문을 생성·수정하지 않는다.

앱 내 전문의 원본은 `apps/mobile/assets/legal/{privacy,terms}.ko.json`이다. 설정과 최초 동의 화면에서는 공개 URL이나 인터넷 없이 이 원본을 읽는다. `python3 scripts/render_legal_documents.py`로 같은 내용의 한국어 HTML을 생성한 뒤 아래 공개 빌더에 전달한다. 문서의 `publication_status=review`는 공개 승인과 구분하며, 빌더는 승인 플래그와 해시가 있어도 검토본을 거절한다. 실제 문구·운영 계약·시행일을 확정한 후 원본 승인 상태와 생성 HTML의 승인 해시를 함께 갱신한다.

## 지금 준비된 범위

- `/`: 보호자 도움말 첫 화면
- `/support/`: 생성 상태, 복구 코드, 문의 안내
- `/delete-account/`: 앱 내 삭제와 앱 밖 이메일 삭제 요청 시작 동선
- `/privacy/`, `/terms/`: 별도 승인된 HTML을 해시 검증 후 그대로 복사

삭제 문의 이메일은 요청의 시작이다. 운영자는 인증정보를 이메일로 요구하거나 소유 확인 없이 계정을 지우지 않는다. 안전한 소유 확인·처리·후속 통지의 운영 절차를 검증해야 실제 삭제 지원 완료로 볼 수 있다.

## 비공개 검토본

저장소 루트에서 실행한다. 실제 연락처와 기존 미승인 정책 초안은 표시하지 않는다. 브라우저·서버를 자동 실행하지 않는다.

```bash
python3 scripts/build_public_support_site.py \
  --config apps/public-site/config.example.json \
  --output-dir docs/acceptance/public-site-private-preview \
  --private-preview
```

## 공개용 파일 생성

운영자가 확인한 HTTPS 사이트 주소와 지원 이메일, 승인된 개인정보처리방침·약관 HTML의 파일 경로와 SHA-256을 비공개 설정 파일에 기록한다. `support_contact_verified`와 `legal_copy_approved`는 실제 확인/승인의 기록이며 도구가 대신 검증하거나 승인하지 않는다. 기존 `docs/privacy-policy.*.html`은 승인된 최종 문서라고 가정하지 않는다.

```bash
python3 scripts/build_public_support_site.py \
  --config /absolute/private/public-site-config.json \
  --output-dir /absolute/private/public-site-production
```

필수 값 누락, 예시 주소, 회신 불가 이메일, 미승인 정책, 정책 해시 불일치, 활성 스크립트가 포함된 정책이면 출력 폴더를 만들기 전에 종료 코드 1로 중단한다. 기존 출력 폴더는 덮어쓰지 않는다. 비공개 미리보기는 `noindex`/robots 차단과 `publishable=false` 기록이 있으며 공개 대상으로 사용하지 않는다. 생성 명령에는 호스팅·DNS·배포·메시지 전송 기능이 없다.

활성 콘텐츠 검사는 스크립트·임베드·폼 태그, 이벤트 속성, HTML 엔티티나 공백으로 숨긴 JavaScript 링크를 잡는 추가 방어다. 모든 HTML 공격을 판정하는 보안 검토나 정책 원문 승인을 대신하지 않는다.

정책 승인과 실제 지원 연락처가 연결된 후 공개 호스팅의 HTTPS, 로그인 없는 접근, 문의 작성 링크, 삭제 요청 접수와 소유 확인을 실제로 검증한다. 모바일에는 `PRIVACY_POLICY_URL`과 `TERMS_OF_SERVICE_URL`을 새 빌드에 명시적으로 전달하고, 스토어에는 지원 URL과 필요한 삭제 리소스 URL을 등록한다.
