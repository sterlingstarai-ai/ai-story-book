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
)

print_help() {
  cat <<EOF
Environment Variable Validation Script

Usage:
  ./scripts/check-env.sh [--mode local|production|ci] [--env-file PATH]
  ./scripts/check-env.sh --ci

Modes:
  local       Validate API runtime variables (default)
  production  Validate infra/docker-compose production variables
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

  if [ "$has_errors" = true ]; then
    exit 1
  fi
}

run_runtime_checks() {
  local required_vars_name="$1"
  local optional_vars_name="$2"
  local -n required_vars="$required_vars_name"
  local -n optional_vars="$optional_vars_name"
  local has_errors=false

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

  if [ "$has_errors" = true ]; then
    log_fail "Validation FAILED"
    exit 1
  fi
  log_ok "Validation PASSED"
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
  *)
    log_fail "Unknown mode: $MODE"
    exit 1
    ;;
esac
