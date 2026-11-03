# 제공자 키 전송: IAP 세션과 GCE 작업 재대조

`scripts/provider_iap_sender_session.py`는 인스턴스 전용 임시 공개 SSH 행을
GCE fingerprint CAS로 넣고, IAP 경유 strict host-key pin으로 전용 SSH master를
인증한 다음 자기 행의 삭제·재조회와 로컬 개인키 삭제를 모두 확인해야만 기존
`provider_key_transfer.transfer()`가 키체인에 접근하도록 구성한 후보이다.
실제 GCE 경로는 명시적 실행 요청과 아래 대상·기록·시간 검사를 통과해야만
진행한다. 준비된 경로를 실제로 실행하거나 운영 키를 전송한 적은 없으며,
이 코드는 503을 해결한 증거가 아니다.

`provider_iap_session_ledger.py`는 소유자 전용 디렉터리와 비차단 공유 잠금,
세션 open/closed와 GCE operation 시작·operation ID·terminal 상태의 0600
append-only 기록 및 파일·디렉터리 fsync를 제공한다. 이전 open session이나
완료되지 않은 operation, 손상 또는 미상 파일이 있으면 다음 세션을 차단한다.
기록은 공개 SSH 행·request ID·대상과 임시 디렉터리 등만 포함하며 토큰이나
provider 키는 포함하지 않는다. 같은 OS 사용자에 의한 변조는 방어하지 못한다.

`provider_iap_reconcile.py`는 알려진 자기 ledger 항목 하나에 대해 고정된
프로젝트·zone·인스턴스 ID, request ID, operation ID, GCE target link 및 status를
읽기 전용으로 대조한다. GCE가 정확한 `setMetadata` 작업을 오류 없이 DONE으로
보고하고 현재 자기 SSH 행도 의도한 삽입/삭제 상태와 일치하는 경우에만 로컬
terminal 성공을 기록한다. 신청 당시 fingerprint와 현재 fingerprint의 동일 여부는
관측값일 뿐 그 자체로 안전성을 증명하지 않는다. pending, 실패, 미발견, 복수,
target 불일치 및 손상 기록은 자동 완료하지 않는다. 세션 자체를 닫거나 GCE
metadata를 수정하지 않는다.

2026-11-03 현재 소유가 확인된 기존 임시 SSH 저널 23개와 작업 46개를 실제
GCE에서 읽기 전용으로 재대조했다. 모든 작업이 정확한 대상·request ID의
DONE/오류 없음이고 현재 해당 자기 행이 없다. 구형 저널은 제출 fingerprint를
보관하지 않았으므로 그 값은 비교하지 못했다. 이 저널을 새 ledger에 자동
편입하거나 모르는 다른 저널을 완료 처리하지 않았다. 감사는 알려진 정확한
저널 목록, 실행 전후 metadata fingerprint 및 인스턴스 식별자를 확인하며,
누락·미상·진행 중·손상 기록이 발견되면 중단한다.

운영 키 파일 준비의 첫 두 시도는 macOS Keychain 조회가 각각 60초와 180초
동안 응답하지 않아 실패했고, 당시 `provider.key`와 거래 임시 파일은 없었다.
사용자의 키체인 승인 후 세 번째 송신은 성공했다. 백업 잠금 아래 별도 확인한
결과 파일은 정규파일 1000:1000, 0600이며 키 형식 검사에 통과했고 거래 marker와
임시 파일은 없다. 세 송신 세션의 새 ledger는 닫혔고 GCE 작업 6개도 DONE 및
해당 SSH 행 부재를 읽기 전용으로 재확인했다. 기존 운영 키나 서비스는 변경하지
않았으며 API/worker가 새 키를 사용하도록 전환된 것은 아니다.

합성 reconciliation·ledger·sender session·구형 저널 감사 검사는 45개 통과했다.
실 sender 경로에는 새 ledger 잠금을 잡은 뒤 세션·SSH 개인키 생성 이전에 구형
저널을 감사하는 검사가 연결되어 있다. 이 검사는
fake GCE/IAP/sender를 사용하며, 실제 GCE operation 목록 필터·실패 복구, 이전
별도 도구와의 실제 동시 실행, 비정상 종료 뒤 개인키/터널 정리 및 원격 키
수신 복구의 통합 검증은 아니다. 조회 결과가 없다는 사실만으로 GCE 작업이
없거나 나중에 완료되지 않는다고 판단하지 않는다. 임시 SSH 키 만료는 Mac 시계를 사용하므로,
고정된 GCE HTTPS 응답의 단일 GMT Date와 wall/monotonic 및 왕복 시간을 대조해 최악
시차가 15초를 넘거나 측정이 모호하면 metadata POST 전에 차단하도록 추가했다.
키 수명은 4분 30초다. 시간 비교는 실제 GCE HTTPS 응답으로 읽기 전용 확인했으나,
서버 Date의 신뢰 경계는 별도 고려가 필요하다. 구형 별도 SSH 도구는 새 ledger
잠금을 공유하지 않으므로 동시에 실행될 수 있다. 독립 writer가 최신 상태를 읽고
fingerprint CAS를 준수한다면 충돌 시 재조회하거나 중단하고, 각 도구는 자기 행만
제거한다. 따라서 writer의 부재가 필수 조건은 아니지만 반복 충돌이나 미확정 응답은
작업을 중단시키고 복구가 필요하다. 권한 있는 관리자가 의도적으로 metadata를
덮어쓰는 경우는 CAS 또는 로컬 잠금으로 차단할 수 없는 별도의 신뢰 경계다.
