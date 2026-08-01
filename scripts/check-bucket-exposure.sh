#!/bin/bash
# S5: 민감 미디어(아동 사진·가족 음성)가 익명으로 접근 가능한지 실환경 확인.
#
# 코드는 ACL을 지정하지 않으므로(put_object에 ACL 인자 없음, ensure_bucket_exists도
# "configure access policy manually" 경고만) 실제 공개 여부는 **프로덕션 버킷 정책**이
# 결정한다. 이 스크립트는 그 정책의 실효를 인증 없이 직접 확인한다.
#
# 사용: ./scripts/check-bucket-exposure.sh https://media.example.com <민감객체키>
#   예: ./scripts/check-bucket-exposure.sh "$S3_PUBLIC_URL" "voice-samples/<uid>/xxx.m4a"
#
# 판정:
#   200 → 익명 접근 가능(=public-read). 아동 biometric-adjacent PII가 무인증 노출 →
#         서명 URL 또는 인증 프록시로 전환 필요(공유 페이지는 이미 /share/{token}/img 프록시 사용).
#   403/404 → 익명 접근 불가(비공개). 저장된 URL은 소유자 인증 API를 통해서만 유통.

set -euo pipefail

BASE="${1:-${S3_PUBLIC_URL:-}}"
KEY="${2:-}"

if [ -z "$BASE" ] || [ -z "$KEY" ]; then
  echo "usage: $0 <s3_public_url> <object_key>" >&2
  echo "  예: $0 https://media.example.com voice-samples/<user>/sample.m4a" >&2
  exit 2
fi

URL="${BASE%/}/${KEY#/}"
echo "[check] 익명(무인증) GET: $URL"

# 자격증명·쿠키 없이 요청 — 프로덕션 정책의 익명 접근 허용 여부만 본다.
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$URL" || echo "000")"
echo "[result] HTTP $CODE"

case "$CODE" in
  200)
    echo "[VERDICT] PUBLIC — 민감 미디어가 무인증으로 접근 가능합니다."
    echo "          아동 사진·가족 음성은 만료 없는 안정 URL이라 링크 유출 시 영구 재생 가능."
    echo "          조치: 버킷을 비공개로 전환하고 서명 URL(presigned) 또는 인증 프록시 도입."
    exit 1
    ;;
  403|404)
    echo "[VERDICT] NOT PUBLIC — 익명 접근이 차단되어 있습니다(정상)."
    echo "          저장된 공개형 URL은 소유자 인증 API 응답으로만 유통됩니다."
    exit 0
    ;;
  000)
    echo "[VERDICT] UNREACHABLE — 네트워크/호스트 확인 필요(판정 불가)." >&2
    exit 2
    ;;
  *)
    echo "[VERDICT] UNEXPECTED($CODE) — 수동 확인 필요." >&2
    exit 2
    ;;
esac
