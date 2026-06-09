# Final User Input Required (Keys / Accounts Only)

이 문서는 개발 코드 완료 후, 실제 외부 연동 검증에 필요한 **최종 사용자 개입 항목**만 정리합니다.

## 0) Preflight (자동 점검)

```bash
cd /Users/jmac/Desktop/ai-story-book
./scripts/final-external-preflight.sh
```

## 1) Backend `.env` keys

- `APPLE_IAP_SHARED_SECRET`
- `GOOGLE_PLAY_PACKAGE_NAME`
- `GOOGLE_PLAY_ACCESS_TOKEN`
- `GOOGLE_PLAY_SERVICE_ACCOUNT_JSON` 또는 `GOOGLE_PLAY_SERVICE_ACCOUNT_FILE`
- `IAP_VERIFICATION_MODE=strict` (최종 검증 시)

- `PRINTFUL_API_KEY`
- `PRINTFUL_SYNC_VARIANT_ID`
- `POD_MODE=strict` (최종 검증 시)

- `KAKAO_NATIVE_APP_KEY` (mobile build-time)
- `ADMOB_REWARDED_AD_UNIT_ANDROID` (mobile build-time)
- `ADMOB_REWARDED_AD_UNIT_IOS` (mobile build-time)

## 2) Mobile build command (with keys)

```bash
cd /Users/jmac/Desktop/ai-story-book/apps/mobile
flutter build apk --release \
  --dart-define=KAKAO_NATIVE_APP_KEY=YOUR_KAKAO_KEY \
  --dart-define=ADMOB_REWARDED_AD_UNIT_ANDROID=YOUR_ADMOB_ANDROID_UNIT \
  --dart-define=ADMOB_REWARDED_AD_UNIT_IOS=YOUR_ADMOB_IOS_UNIT
```

## 3) Backend strict verification smoke

```bash
cd /Users/jmac/Desktop/ai-story-book
python3 -m pytest apps/api/tests/test_phase_new_endpoints.py -q
python3 -m pytest apps/api/tests -q
```

## 4) Sandbox verification (manual)

- Apple Sandbox 결제 후 `/v1/iap/verify` 응답이 `verification_source=apple_store` 인지 확인
- Google 테스트 결제 후 `/v1/iap/verify` 응답이 `verification_source=google_play` 인지 확인
- POD 주문 생성 후 `/v1/pod/orders/{order_id}`에서 `sync_source=printful` 및 상태 전이 확인
