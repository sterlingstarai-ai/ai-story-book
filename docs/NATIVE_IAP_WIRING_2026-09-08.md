# 디지털 결제 구현 상태 — 2026-09-08

사용자의 추가 결제·스토어 등록 없이 서버 및 앱 연결 코드를 완성했다. 실제 상점 거래와 공개 HTTPS 알림 수신은 계정·배포 이후 검증해야 한다. 테스트에서 생성한 영수증과 공급자 응답은 실제 유료 결제의 증거가 아니다.

## 구현

- Apple StoreKit 2 서명 거래를 Apple 공식 `app-store-server-library`로 검증한다. 거래·상품·앱 ID·환경·인증서 체인·서명을 확인하며 취소/환불 거래는 지급하지 않는다. 구형 `verifyReceipt`는 기존 영수증 복원에 유지한다. 앱은 StoreKit 1 강제를 해제하고 유지관리되는 플러그인 기본 경로를 사용한다.
- Apple V2 `POST /v1/iap/notifications/apple`은 `signedPayload`와 내부 거래/갱신 JWS를 각각 검증한다. 공개 Apple 루트 인증서 G2/G3를 번들에 포함했으므로 별도 인증서 다운로드는 필요 없다.
- Google `POST /v1/iap/notifications/google`은 Pub/Sub OIDC 서명·대상 audience·검증된 발신 서비스 계정 이메일을 확인한 다음 Publisher `subscriptionsv2.get`으로 현재 상태를 재조회한다. 알림의 이벤트 번호만으로 권한을 지급하지 않는다. 예약된 상품 교체 항목은 아직 성공 주문이 없으므로 현재 권한으로 간주하지 않는다.
- 스토어 구독 만료는 실제 검증값을 저장한다. 복원할 때 30일을 새로 주거나 날짜가 지났다는 이유만으로 자동 리필하던 경로를 제거했다. 실제 갱신 거래마다 크레딧을 한 번만 지급한다.
- 먼저 도착한 알림을 보관하고 영수증 검증 후 다시 적용한다. 이전 결제 주기의 환불은 해당 주기의 지급액만 회수하고 새 결제 주기를 종료하지 않는다. 같은 주기에 상품을 올렸다 내리는 반복으로 크레딧을 추가 발급할 수 없도록 주기별 최대 지급량을 전달한다.
- 앱 시작 후 결제 화면을 열지 않아도 미완료 구매를 검증·복구한다. 실패 시 미승인 상태를 보존하고 앱 복귀 시 재시도한다. 화면과 전역 리스너가 동시에 같은 거래를 받아도 검증/소비 요청을 중복 실행하지 않는다.
- 스토어의 실제 현지화 가격을 조회해 표시하며, 조회되지 않은 가격을 원화 상수로 대신 표시하지 않는다.

## 가격 정본

`docs/appstore/iap-catalog.json`에 아직 등록하지 않은 스토어 상품을 준비했다. 베이직 월 24,900원/5권, 프리미엄 월 44,900원/10권, 크레딧 팩 1/5/10권은 각각 5,900/27,900/52,900원을 등록 기준으로 삼는다. 실제 스토어 가격·환율·수수료는 등록 및 운영 시 다시 확인한다.

이전 6,900원/10권·14,900원/30권은 최근 실제 생성 표본의 약 US$1.2/권보다 책당 수입이 낮았다. 이번 계획에서는 환율 1,500원/US$와 판매가의 40% 차감 여유를 **계획 가정**으로 두었다(현재 환율이나 특정 수수료/세율 주장 아님). 새 구독의 권당 차감 후 수입 약 2,988원/2,694원은 표본 기반 AI 비용 약 1,800원보다 높다. 음성·저장소·지원·실제 청구 비용을 지속 측정해야 하며 표본 하나가 모든 책의 원가를 보장하지 않는다. 기존 저장된 구독의 지급량은 보존한다.

## 실제 연결에 필요한 설정과 검증

Apple: 실제 `APPLE_APP_ID`, `APPLE_BUNDLE_ID`, `APPLE_NOTIFICATION_ENVIRONMENT`(Production 또는 Sandbox), legacy 복원을 위한 공유 암호. V2 알림 URL을 App Store Connect에 등록한다. `APPLE_ROOT_CA_PATHS`는 선택이며 기본 공개 인증서 번들을 사용한다.

Google: 실제 package name, Publisher API 권한이 있는 서비스 계정, RTDN topic/push 구독, `GOOGLE_RTDN_AUDIENCE`와 `GOOGLE_RTDN_SERVICE_ACCOUNT_EMAIL`. push audience는 실제 알림 HTTPS endpoint를 사용한다.

스토어 sandbox에서는 승인된 상품 allowlist를 사용한다. 실제 운영 자격 증명이 없는 상태에서 테스트 영수증 지급을 열거나 feature flag만 켜지 않는다. 각 스토어에서 신규 결제·갱신·취소/만료·환불·계정 복원·서버 응답 지연·중복 알림·플랜 교체를 검증한 뒤 결제 기능을 공개한다. 서명이 유효한 스토어 알림도 DB 실패 시 성공으로 삼키지 않고 재전송 대상으로 남긴다.

공식 근거: [Apple 서버 라이브러리](https://github.com/apple/app-store-server-library-python), [Apple V2 알림 수신](https://developer.apple.com/documentation/appstoreservernotifications/receiving-app-store-server-notifications), [Google RTDN](https://developer.android.com/google/play/billing/rtdn-reference), [Google 인증된 Pub/Sub push](https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions), [Google SubscriptionPurchaseV2](https://developers.google.com/android-publisher/api-ref/rest/v3/purchases.subscriptionsv2).
