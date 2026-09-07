#!/bin/bash
# =============================================================================
# check-env.sh - Environment Variable Validation Script
# =============================================================================
# Usage:
#   ./scripts/check-env.sh
#   ./scripts/check-env.sh --mode production --env-file infra/.env
#   ./scripts/check-env.sh --mode ci
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

MODE="local"
ENV_FILE=""

LOCAL_REQUIRED_VARS=(
  "DATABASE_URL"
  "REDIS_URL"
  "LLM_PROVIDER"
  "IMAGE_PROVIDER"
  "S3_ENDPOINT"
  "S3_ACCESS_KEY"
  "S3_SECRET_KEY"
  "S3_BUCKET"
)

PRODUCTION_REQUIRED_VARS=(
  "DB_USER"
  "DB_PASSWORD"
  "DB_NAME"
  "LLM_PROVIDER"
  "IMAGE_PROVIDER"
  "S3_ENDPOINT"
  "S3_ACCESS_KEY"
  "S3_SECRET_KEY"
  "S3_BUCKET"
  "CORS_ORIGINS"
  "PROD_API_URL"
  # IAP stays strict even during the free beta; enabled purchases require store keys below.
  "IAP_VERIFICATION_MODE"
)

EXTERNAL_REQUIRED_VARS=(
  "DATABASE_URL" "DATABASE_SSL_MODE" "DATABASE_SSL_ROOT_CERT"
  "S3_REGION" "S3_ADDRESSING_STYLE" "S3_AUTO_CREATE_BUCKET"
  "API_IMAGE" "WORKER_IMAGE"
  "LLM_PROVIDER" "IMAGE_PROVIDER" "S3_ENDPOINT" "S3_ACCESS_KEY"
  "S3_SECRET_KEY" "S3_BUCKET" "CORS_ORIGINS" "PROD_API_URL" "IAP_VERIFICATION_MODE"
)

LOCAL_OPTIONAL_VARS=(
  "LLM_API_KEY"
  "IMAGE_API_KEY"
  "AUDIO_FEATURE_ENABLED"
  "TTS_PROVIDER"
  "STT_PROVIDER"
  "ADMIN_API_KEY"
)

# H1/G9: 오디오는 GA에서 기본 비활성(AUDIO_FEATURE_ENABLED=false)이라 TTS/STT를
# 무조건 필수로 두지 않는다. AUDIO_FEATURE_ENABLED=true로 켜면 TTS_PROVIDER(google/
# elevenlabs)·STT_PROVIDER(openai/google) 라이브 구성이 필수가 되며, 이는 런타임
# /health/ready(tts_provider_not_live / stt_provider_not_live)가 최종 게이트한다.
PRODUCTION_OPTIONAL_VARS=(
  "LLM_API_KEY"
  "IMAGE_API_KEY"
  "AUDIO_FEATURE_ENABLED"
  "TTS_PROVIDER"
  "STT_PROVIDER"
  "S3_PUBLIC_URL"
  "ADMIN_API_KEY"
  "APPLE_IAP_SHARED_SECRET"
  "GOOGLE_PLAY_PACKAGE_NAME"
)

print_help() {
  cat <<EOF
Environment Variable Validation Script

Usage:
  ./scripts/check-env.sh [--mode local|production|external|ci] [--env-file PATH]
  ./scripts/check-env.sh --ci

Modes:
  local       Validate API runtime variables (default)
  production  Validate infra/docker-compose production variables
  external    Validate external PostgreSQL/private S3 deployment and release configuration
  ci          Validate repository env examples/schemas
EOF
}

log_ok() {
  echo -e "${GREEN}OK${NC}: $1"
}

log_warn() {
  echo -e "${YELLOW}WARN${NC}: $1"
}

log_fail() {
  echo -e "${RED}FAIL${NC}: $1"
}

load_env_file() {
  local file_path="$1"
  if [ -z "$file_path" ]; then
    return 0
  fi
  if [ ! -f "$file_path" ]; then
    log_fail "Environment file not found: $file_path"
    exit 1
  fi
  echo "Loading environment file: $file_path"
  set -a
  # shellcheck disable=SC1090
  source "$file_path"
  set +a
}

is_placeholder() {
  local value="$1"
  local lowered
  lowered="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  [[ "$lowered" == *"your-"* ]] || [[ "$lowered" == *"change_me"* ]] || [[ "$lowered" == *"example"* ]]
}

check_var() {
  local var_name="$1"
  local required="$2"
  local value="${!var_name:-}"

  if [ -n "$value" ]; then
    if is_placeholder "$value"; then
      log_warn "$var_name appears to use a placeholder value"
      return 1
    fi
    log_ok "$var_name is set"
    return 0
  fi

  if [ "$required" = "true" ]; then
    log_fail "$var_name is required but not set"
    return 1
  fi

  log_warn "$var_name is not set"
  return 0
}

run_ci_checks() {
  local has_errors=false

  echo "CI Mode: Validating repository env contracts..."

  if [ -f "$ROOT_DIR/env.schema.json" ]; then
    log_ok "env.schema.json exists"
  else
    log_warn "env.schema.json not found (optional)"
  fi

  if [ -f "$ROOT_DIR/apps/api/.env.example" ]; then
    log_ok "apps/api/.env.example exists"
  else
    log_fail "apps/api/.env.example not found"
    has_errors=true
  fi

  if [ -f "$ROOT_DIR/infra/.env.example" ]; then
    log_ok "infra/.env.example exists"
  else
    log_fail "infra/.env.example not found"
    has_errors=true
  fi

  if ! python3 "$ROOT_DIR/scripts/validate_rate_limit_contract.py"; then
    has_errors=true
  fi
  if ! python3 "$ROOT_DIR/scripts/validate_provider_runtime_contract.py"; then
    has_errors=true
  fi

  if [ "$has_errors" = true ]; then
    exit 1
  fi
}

run_runtime_checks() {
  local required_vars_name="$1"
  local optional_vars_name="$2"
  # macOS ships Bash 3.2, which has no nameref (local -n).
  local required_vars=()
  local optional_vars=()
  case "$required_vars_name" in
    LOCAL_REQUIRED_VARS) required_vars=("${LOCAL_REQUIRED_VARS[@]}") ;;
    PRODUCTION_REQUIRED_VARS) required_vars=("${PRODUCTION_REQUIRED_VARS[@]}") ;;
    EXTERNAL_REQUIRED_VARS) required_vars=("${EXTERNAL_REQUIRED_VARS[@]}") ;;
    *) return 1 ;;
  esac
  case "$optional_vars_name" in
    LOCAL_OPTIONAL_VARS) optional_vars=("${LOCAL_OPTIONAL_VARS[@]}") ;;
    PRODUCTION_OPTIONAL_VARS) optional_vars=("${PRODUCTION_OPTIONAL_VARS[@]}") ;;
    *) return 1 ;;
  esac
  local has_errors=false

  if [ -n "${RATE_LIMIT:-}" ]; then
    log_fail "RATE_LIMIT is unsupported; use RATE_LIMIT_REQUESTS and RATE_LIMIT_READ_REQUESTS"
    has_errors=true
  fi
  local rate_writes="${RATE_LIMIT_REQUESTS:-10}"
  local rate_reads="${RATE_LIMIT_READ_REQUESTS:-120}"
  local rate_window="${RATE_LIMIT_WINDOW:-60}"
  if [[ ! "$rate_writes" =~ ^[1-9][0-9]*$ ]] || [[ ! "$rate_reads" =~ ^[1-9][0-9]*$ ]] || [[ ! "$rate_window" =~ ^[1-9][0-9]*$ ]]; then
    log_fail "Rate limits and window must be positive integers"
    has_errors=true
  elif [ "$((rate_reads * 60))" -lt "$((rate_window * 60))" ]; then
    log_fail "Read rate must support at least 60 requests per minute for progress polling and navigation"
    has_errors=true
  fi

  echo "Checking required variables..."
  echo "----------------------------------------"
  for var_name in "${required_vars[@]}"; do
    if ! check_var "$var_name" "true"; then
      has_errors=true
    fi
  done

  echo ""
  echo "Checking optional variables..."
  echo "----------------------------------------"
  for var_name in "${optional_vars[@]}"; do
    check_var "$var_name" "false" || true
  done

  if ! validate_provider_settings; then
    has_errors=true
  fi

  if [ "$has_errors" = true ]; then
    log_fail "Validation FAILED"
    exit 1
  fi
  log_ok "Validation PASSED"
}

flag_enabled() {
  local value
  value="$(printf '%s' "${1:-false}" | tr '[:upper:]' '[:lower:]')"
  case "$value" in true|1|yes|on) return 0 ;; *) return 1 ;; esac
}

validate_provider_settings() {
  local failed=false
  case "${S3_ADDRESSING_STYLE:-path}" in
    path|virtual|auto) ;;
    *) log_fail "S3_ADDRESSING_STYLE must be path, virtual or auto"; failed=true ;;
  esac
  case "${DATABASE_SSL_MODE:-}" in
    ""|disable|allow|prefer|require|verify-ca|verify-full) ;;
    *) log_fail "DATABASE_SSL_MODE is not supported"; failed=true ;;
  esac
  for flag_name in PURCHASES_ENABLED POD_ORDERING_ENABLED AUDIO_FEATURE_ENABLED ILLUSTRATION_QUALITY_ENABLED PHOTO_PROCESSING_ENABLED S3_AUTO_CREATE_BUCKET; do
    local flag_value
    flag_value="$(printf '%s' "${!flag_name:-false}" | tr '[:upper:]' '[:lower:]')"
    case "$flag_value" in true|false|1|0|yes|no|on|off) ;;
      *) log_fail "$flag_name must be a boolean"; failed=true ;;
    esac
  done
  case "${LLM_PROVIDER:-}" in
    openai|anthropic|gemini|mock) ;;
    *) log_fail "LLM_PROVIDER is not supported"; failed=true ;;
  esac
  case "${IMAGE_PROVIDER:-}" in
    openai|gemini|replicate|fal|mock) ;;
    *) log_fail "IMAGE_PROVIDER is not supported"; failed=true ;;
  esac
  case "${OPENAI_IMAGE_QUALITY:-medium}" in
    low|medium|high|auto) ;;
    *) log_fail "OPENAI_IMAGE_QUALITY must be low, medium, high or auto"; failed=true ;;
  esac
  case "${PHOTO_ANALYSIS_PROVIDER:-openai}" in
    openai|mock) ;;
    *) log_fail "PHOTO_ANALYSIS_PROVIDER is not supported"; failed=true ;;
  esac
  if flag_enabled "${PHOTO_PROCESSING_ENABLED:-false}"; then
    if [ "${PHOTO_ANALYSIS_PROVIDER:-openai}" != openai ] || [ "${IMAGE_PROVIDER:-}" != openai ] ||
       [ "${LLM_PROVIDER:-}" != openai ] || ! flag_enabled "${ILLUSTRATION_QUALITY_ENABLED:-false}"; then
      log_fail "Enabled photo processing requires approved OpenAI analysis, image and QA configuration"; failed=true
    fi
    case "${IMAGE_MODEL:-}" in gpt-image-*) ;; *) log_fail "Photo processing requires GPT Image reference support"; failed=true ;; esac
    check_var PHOTO_ANALYSIS_API_KEY true || failed=true
    check_var PHOTO_ANALYSIS_MODEL true || failed=true
  fi
  if [ "$MODE" = production ] || [ "$MODE" = external ]; then
    if ! flag_enabled "${ILLUSTRATION_QUALITY_ENABLED:-false}"; then
      log_fail "Production requires ILLUSTRATION_QUALITY_ENABLED=true"; failed=true
    fi
    if [ "${IAP_VERIFICATION_MODE:-}" != strict ]; then
      log_fail "Production requires IAP_VERIFICATION_MODE=strict"; failed=true
    fi
    if [ "${LLM_PROVIDER:-}" = mock ] || [ "${IMAGE_PROVIDER:-}" = mock ]; then
      log_fail "Production requires live LLM and image providers"; failed=true
    fi
    for var_name in LLM_API_KEY IMAGE_API_KEY LLM_MODEL IMAGE_MODEL; do
      check_var "$var_name" true || failed=true
    done
  fi
  if flag_enabled "${ILLUSTRATION_QUALITY_ENABLED:-false}"; then
    if [ "${LLM_PROVIDER:-}" != openai ]; then
      log_fail "Illustration review requires an OpenAI vision model"; failed=true
    else
      case "${LLM_MODEL:-}" in
        gpt-5.6-sol|gpt-6-astra|gpt-5.6) ;;
        *) log_fail "Illustration review model is not supported"; failed=true ;;
      esac
    fi
  fi
  if { [ "$MODE" = production ] || [ "$MODE" = external ]; } && flag_enabled "${PURCHASES_ENABLED:-false}"; then
    for var_name in APPLE_IAP_SHARED_SECRET APPLE_BUNDLE_ID GOOGLE_PLAY_PACKAGE_NAME IAP_WEBHOOK_SECRET; do
      check_var "$var_name" true || failed=true
    done
    if [ -z "${GOOGLE_PLAY_ACCESS_TOKEN:-}" ] && [ -z "${GOOGLE_PLAY_SERVICE_ACCOUNT_JSON:-}" ] &&
       { [ -z "${GOOGLE_PLAY_SERVICE_ACCOUNT_FILE:-}" ] || [ ! -f "${GOOGLE_PLAY_SERVICE_ACCOUNT_FILE:-}" ]; }; then
      log_fail "Enabled purchases require Google Play authentication"; failed=true
    fi
  fi
  if [ "${LLM_PROVIDER:-}" = gemini ] && [[ "${LLM_MODEL:-}" != gemini-* ]]; then
    log_fail "LLM_MODEL must match the Gemini provider"; failed=true
  fi
  if [ "${LLM_PROVIDER:-}" = anthropic ] && [[ "${LLM_MODEL:-}" != claude-* ]]; then
    log_fail "LLM_MODEL must match the Anthropic provider"; failed=true
  fi
  if [ "${IMAGE_PROVIDER:-}" = gemini ] && [[ "${IMAGE_MODEL:-}" != gemini-*-image* ]]; then
    log_fail "IMAGE_MODEL must be an explicitly selected Gemini image model"; failed=true
  fi
  if { [ "$MODE" = production ] || [ "$MODE" = external ]; } && flag_enabled "${POD_ORDERING_ENABLED:-false}"; then
    if [ "${POD_MODE:-local}" != strict ]; then
      log_fail "POD_ORDERING_ENABLED requires POD_MODE=strict"; failed=true
    fi
    check_var PRINTFUL_API_KEY true || failed=true
    check_var PRINTFUL_SYNC_VARIANT_ID true || failed=true
  fi
  [ "$failed" = false ]
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --ci)
      MODE="ci"
      shift
      ;;
    --help|-h)
      print_help
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      print_help
      exit 1
      ;;
  esac
done

echo "========================================"
echo "Environment Variable Validation"
echo "========================================"
echo "Mode: $MODE"
echo ""

case "$MODE" in
  ci)
    run_ci_checks
    ;;
  local)
    if [ -z "$ENV_FILE" ]; then
      if [ -f "$ROOT_DIR/apps/api/.env" ]; then
        ENV_FILE="$ROOT_DIR/apps/api/.env"
      fi
    fi
    load_env_file "$ENV_FILE"
    run_runtime_checks LOCAL_REQUIRED_VARS LOCAL_OPTIONAL_VARS
    ;;
  production)
    if [ -z "$ENV_FILE" ]; then
      if [ -f "$ROOT_DIR/infra/.env" ]; then
        ENV_FILE="$ROOT_DIR/infra/.env"
      elif [ -f "$ROOT_DIR/.env" ]; then
        ENV_FILE="$ROOT_DIR/.env"
      fi
    fi
    load_env_file "$ENV_FILE"
    run_runtime_checks PRODUCTION_REQUIRED_VARS PRODUCTION_OPTIONAL_VARS
    ;;
  external)
    # Explicit file selection prevents accidentally treating local API credentials
    # as the external host configuration. The final gate only inspects values.
    if [ -z "$ENV_FILE" ]; then
      log_fail "External mode requires --env-file PATH"
      exit 1
    fi
    load_env_file "$ENV_FILE"
    run_runtime_checks EXTERNAL_REQUIRED_VARS PRODUCTION_OPTIONAL_VARS
    bash "$ROOT_DIR/scripts/final-external-preflight.sh" --env-file "$ENV_FILE"
    ;;
  *)
    log_fail "Unknown mode: $MODE"
    exit 1
    ;;
esac
