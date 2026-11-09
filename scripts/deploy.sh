#!/bin/bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILES=("infra/docker-compose.prod.yml")
ROLLBACK_COMPOSE_FILES=()
CUSTOM_COMPOSE_FILES=false
ENV_FILE=""
ROLLBACK_ENV_FILE=""
ROLLBACK_ENV_SHA=""
IMAGE_TAG_OVERRIDE=""
COMPOSE_CMD=()
PREV_API_CONTAINER=""
PREV_WORKER_CONTAINER=""
PREV_API_ID=""
PREV_WORKER_ID=""
PREV_API_HASH=""
PREV_WORKER_HASH=""
# Keep the caller's Docker and TLS settings, without passing the new release's
# exported application variables into the previous environment.
ROLLBACK_HOST_ENV=()
for name in PATH HOME DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_TLS_VERIFY DOCKER_CERT_PATH \
    COMPOSE_PROJECT_NAME SSL_CERT_FILE SSL_CERT_DIR CURL_CA_BUNDLE HEALTH_WAIT_RETRIES HEALTH_WAIT_INTERVAL; do
  if [ "${!name+x}" = x ]; then
    ROLLBACK_HOST_ENV+=("$name=${!name}")
  fi
done

log_info() {
  echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
  echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
  echo -e "${RED}[ERROR]${NC} $1"
}

print_help() {
  cat <<EOF
Usage: ./scripts/deploy.sh [--env-file PATH] [--rollback-env-file PATH] [--compose-file PATH] [--rollback-compose-file PATH] [--image-tag TAG] <command>

Use --rollback-env-file with deploy when the release changes runtime settings.
The previous private env file must match the running API and worker.
Repeat --compose-file to layer overrides after the base file.
Repeat --rollback-compose-file for the previous base and overrides when the Compose files change.

Commands:
  deploy   Pull images, migrate (before up), roll services, health-check (auto-rollback on failure)
  start    Start all services
  stop     Stop all services
  restart  Restart all services
  logs     Show service logs
  status   Show service status
  health   Run health checks
  migrate  Run database migrations
  build    Pull configured images (image-based production deploy)
  cleanup  Clean up unused Docker resources
  backup   Write a private, verified PostgreSQL custom-format backup (DB only)
  smoke    Run the stateful smoke journey against configured PROD_API_URL
EOF
}

detect_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
    return
  fi
  log_error "Docker Compose is not installed"
  exit 1
}

resolve_default_env_file() {
  if [ -n "$ENV_FILE" ]; then
    return
  fi
  if [ -f "$ROOT_DIR/infra/.env" ]; then
    ENV_FILE="infra/.env"
    return
  fi
}

load_env_file() {
  if [ -z "$ENV_FILE" ]; then
    log_error "No environment file found. Use --env-file or create infra/.env"
    exit 1
  fi
  if [[ "$ENV_FILE" != /* ]]; then
    ENV_FILE="$ROOT_DIR/$ENV_FILE"
  fi
  if [ ! -f "$ENV_FILE" ]; then
    log_error "Environment file ($ENV_FILE) not found"
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
}

compose() {
  (
    cd "$ROOT_DIR"
    local file flags=()
    for file in "${COMPOSE_FILES[@]}"; do flags+=(-f "$file"); done
    "${COMPOSE_CMD[@]}" --env-file "$ENV_FILE" "${flags[@]}" "$@"
  )
}

infer_repo_path() {
  local remote repo_path
  remote="$(git -C "$ROOT_DIR" config --get remote.origin.url || true)"
  if [[ "$remote" =~ github\.com[:/](.+/.+)(\.git)?$ ]]; then
    repo_path="${BASH_REMATCH[1]}"
    repo_path="${repo_path%.git}"
    printf '%s' "$(printf '%s' "$repo_path" | tr '[:upper:]' '[:lower:]')"
    return 0
  fi
  return 1
}

configure_images() {
  if [ -z "$IMAGE_TAG_OVERRIDE" ]; then
    return
  fi

  local repo_path
  repo_path="${IMAGE_REPOSITORY:-}"
  if [ -z "$repo_path" ]; then
    repo_path="$(infer_repo_path || true)"
  fi
  if [ -z "$repo_path" ]; then
    repo_path="sterlingstarai-ai/ai-story-book"
  fi

  # An explicit release tag wins over stale API_IMAGE/WORKER_IMAGE values in .env.
  export API_IMAGE="ghcr.io/${repo_path}/api:${IMAGE_TAG_OVERRIDE}"
  export WORKER_IMAGE="ghcr.io/${repo_path}/worker:${IMAGE_TAG_OVERRIDE}"
  export IMAGE_TAG="$IMAGE_TAG_OVERRIDE"
}

check_requirements() {
  log_info "Checking requirements..."
  if ! command -v docker >/dev/null 2>&1; then
    log_error "Docker is not installed"
    exit 1
  fi
  detect_compose
  resolve_default_env_file
  load_env_file
  configure_images
  log_info "Using env file: $ENV_FILE"
  log_info "Using compose files: ${COMPOSE_FILES[*]}"
}

check_free_beta_release() {
  local trial
  trial="$(printf '%s' "${FREE_PLAN_FIRST_BOOK_TRIAL:-false}" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  case "$trial" in
    true|1|yes|on|t|y)
      log_info "Checking free beta release configuration..."
      "$ROOT_DIR/scripts/final-external-preflight.sh" --free-beta
      ;;
  esac
}

pull_images() {
  log_info "Pulling configured images..."
  if [ -n "$ROLLBACK_ENV_FILE" ]; then
    compose pull api worker
  else
    compose pull
  fi
  log_info "Images pulled successfully"
}

run_migrations() {
  log_info "Running database migrations..."
  if [ -n "$ROLLBACK_ENV_FILE" ]; then
    compose run --rm --no-deps api alembic upgrade head
  else
    compose run --rm api alembic upgrade head
  fi
  log_info "Migrations completed"
}

start_services() {
  log_info "Starting services..."
  if [ -n "$ROLLBACK_ENV_FILE" ]; then
    compose up -d --no-deps --pull never api worker || return $?
  else
    compose up -d || return $?
  fi
  log_info "Services started"
}

stop_services() {
  log_info "Stopping services..."
  compose down
  log_info "Services stopped"
}

restart_services() {
  log_info "Restarting services..."
  compose restart
  log_info "Services restarted"
}

show_logs() {
  compose logs -f
}

show_status() {
  log_info "Service status:"
  compose ps
}

cleanup() {
  # M26: 앱 named volume(postgres-data/redis-data/minio-data)은 절대 삭제하지 않는다.
  # 이전의 무조건 volume-prune 호출은 compose down 후 미참조 상태의 DB 볼륨을 구식
  # 엔진에서 영구 삭제할 수 있어 제거했다. 컨테이너/이미지/네트워크만 정리(--volumes 미사용).
  log_info "Cleaning up unused Docker resources (containers/images/networks only)..."
  docker system prune -f
  log_info "Cleanup completed"
}

backup_db() {
  (
  umask 077
  if ! compose config --services | grep -Fxq postgres; then
    log_error "External database: use scripts/backup_external.py and docs/BACKUP_RESTORE.md; this command requires an internal postgres service"
    return 1
  fi
  log_info "Backing up database..."
  # The private directory is ignored by Git. Publish only a complete, readable dump.
  local backup_dir backup_file partial_file
  backup_dir="$ROOT_DIR/backups"
  (
    umask 077
    mkdir -p "$backup_dir"
  )
  chmod 700 "$backup_dir"
  partial_file="$(mktemp "$backup_dir/postgres_$(date -u +%Y%m%dT%H%M%SZ)_XXXXXX")"
  trap 'rm -f "${partial_file:-}"' EXIT
  backup_file="${partial_file}.dump"
  if ! compose exec -T postgres pg_dump --format=custom --no-owner --no-privileges \
      -U "$DB_USER" "$DB_NAME" >"$partial_file" ||
     ! compose exec -T postgres pg_restore --list <"$partial_file" >/dev/null; then
    rm -f "$partial_file"
    log_error "Database backup failed; incomplete output removed"
    return 1
  fi
  mv "$partial_file" "$backup_file"
  log_info "Database backed up to $backup_file"
  log_warn "This is DB-only. Keep matching private media and deletion records; see docs/BACKUP_RESTORE.md"
  )
}

require_production_url() {
  # Do not follow a redirect or accept a localhost TLS certificate mismatch as health.
  if [[ "${PROD_API_URL:-}" != https://* ]] ||
     [[ "$PROD_API_URL" == *[\?\#@\ ]* ]] ||
     [[ "${PROD_API_URL#https://}" == */* ]]; then
    log_error "PROD_API_URL must be an HTTPS origin without path, query or credentials"
    return 1
  fi
  if [ -z "${PROD_API_URL#https://}" ]; then
    log_error "PROD_API_URL needs a hostname"
    return 1
  fi
}

probe_health() {
  local code
  code="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --connect-timeout 5 --max-time 15 --proto '=https' "${PROD_API_URL}$1" 2>/dev/null)" || return 1
  [ "$code" = 200 ]
}

# #5: 앱이 리슨할 때까지 대기한다. `compose up -d`는 컨테이너 '기동 시작'에서 리턴할 뿐
# 앱 리슨을 기다리지 않고(FastAPI 임포트에 수 초), api 재생성 중 nginx는 502를 반환한다.
# 구 흐름은 up→migrate→health라 migrate 실행 시간이 우연히 대기 역할을 했는데, M26이
# migrate를 앞으로 옮기며 그 암묵 대기가 사라졌다 — 무대기 1회 curl은 사실상 항상 실패하고
# 새로 배선된 자동 롤백까지 발동해 정상 릴리스가 매번 롤백된다.
: "${HEALTH_WAIT_RETRIES:=30}"
: "${HEALTH_WAIT_INTERVAL:=2}"

wait_for_liveness() {
  local attempt=1
  while [ "$attempt" -le "$HEALTH_WAIT_RETRIES" ]; do
    if probe_health /health/live; then
      log_info "Service is live (attempt $attempt)"
      return 0
    fi
    sleep "$HEALTH_WAIT_INTERVAL"
    attempt=$((attempt + 1))
  done
  log_error "Service did not become live within $((HEALTH_WAIT_RETRIES * HEALTH_WAIT_INTERVAL))s"
  return 1
}

wait_for_readiness() {
  local attempt=1
  while [ "$attempt" -le "$HEALTH_WAIT_RETRIES" ]; do
    if probe_health /health/ready; then
      log_info "Readiness check passed (attempt $attempt)"
      return 0
    fi
    sleep "$HEALTH_WAIT_INTERVAL"
    attempt=$((attempt + 1))
  done
  log_error "Readiness did not recover within the deployment wait window"
  return 1
}

workers_respond() {
  local containers container
  containers="$(compose ps --all --quiet worker)" || return 1
  [ -n "$containers" ] || return 1
  while IFS= read -r container; do
    docker exec "$container" sh -c +      'exec timeout --kill-after=2s 12s celery -A src.worker inspect --timeout=4 --destination="celery@$(hostname)" ping' +      >/dev/null 2>&1 || return 1
  done <<< "$containers"
}

wait_for_workers() {
  local attempt=1
  while [ "$attempt" -le "$HEALTH_WAIT_RETRIES" ]; do
    if workers_respond; then
      log_info "Celery workers responded (attempt $attempt)"
      return 0
    fi
    sleep "$HEALTH_WAIT_INTERVAL"
    attempt=$((attempt + 1))
  done
  log_error "Celery workers did not respond through the broker"
  return 1
}

health_check() {
  log_info "Running health checks..."
  require_production_url || return 1
  if ! wait_for_liveness; then
    return 1
  fi
  if probe_health /health/live; then
    log_info "Liveness check passed"
  else
    log_error "Liveness check failed"
    return 1
  fi

  wait_for_readiness || return 1
  wait_for_workers || return 1

  compose ps --format "table {{.Name}}\t{{.Status}}"
}

capture_running_images() {
  PREV_API_CONTAINER="$(compose ps -q api 2>/dev/null | head -1 || true)"
  PREV_WORKER_CONTAINER="$(compose ps -q worker 2>/dev/null | head -1 || true)"
  PREV_API_ID="$(running_image_id "$PREV_API_CONTAINER" || true)"
  PREV_WORKER_ID="$(running_image_id "$PREV_WORKER_CONTAINER" || true)"
  if [ -n "$PREV_API_ID" ] && [ -n "$PREV_WORKER_ID" ]; then
    log_info "Captured running API and worker image IDs for rollback"
  else
    log_warn "Could not capture both running image IDs — image rollback unavailable"
  fi
}

running_image_id() {
  local container="$1" binding
  [ -n "$container" ] || return 1
  binding="$(docker inspect --format '{{.State.Running}} {{.Image}}' "$container" 2>/dev/null)" || return 1
  [[ "$binding" =~ ^true\ sha256:[0-9a-f]{64}$ ]] || return 1
  printf '%s\n' "${binding#true }"
}

restore_previous_images() {
  # Compose can use cached image IDs directly. Pulling the former tags could
  # fetch the same broken release again if those tags moved during deployment.
  export API_IMAGE="$PREV_API_ID" WORKER_IMAGE="$PREV_WORKER_ID"
  local api_hash worker_hash
  api_hash="$(compose config --hash api)" || return 1
  worker_hash="$(compose config --hash worker)" || return 1
  compose up -d --no-deps --pull never api worker || return 1
  service_containers_match api "$PREV_API_ID" "${api_hash#api }" &&
    service_containers_match worker "$PREV_WORKER_ID" "${worker_hash#worker }" || return 1
  health_check
}

service_containers_match() {
  local role="$1" expected_id="$2" expected_hash="$3" containers container running
  [[ "$expected_id" =~ ^sha256:[0-9a-f]{64}$ && "$expected_hash" =~ ^[a-f0-9]{64}$ ]] || return 1
  containers="$(compose ps --all --quiet "$role")" || return 1
  [ -n "$containers" ] || return 1
  while IFS= read -r container; do
    running="$(docker inspect --format '{{.State.Running}} {{.Image}} {{index .Config.Labels "com.docker.compose.config-hash"}}' \
      "$container" 2>/dev/null)" || return 1
    [ "$running" = "true $expected_id $expected_hash" ] || return 1
  done <<< "$containers"
}

rollback_env_sha() {
  python3 -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$1"
}

run_previous_environment() {
  local file flags=()
  if [ -n "${ROLLBACK_COMPOSE_FILES[0]:-}" ]; then
    for file in "${ROLLBACK_COMPOSE_FILES[@]}"; do flags+=(--compose-file "$file"); done
  else
    for file in "${COMPOSE_FILES[@]}"; do flags+=(--compose-file "$file"); done
  fi
  env -i "${ROLLBACK_HOST_ENV[@]}" \
    ASB_ROLLBACK_ENV_SHA="$ROLLBACK_ENV_SHA" \
    ASB_ROLLBACK_PROD_API_URL="$PROD_API_URL" \
    ASB_ROLLBACK_API_CONTAINER="$PREV_API_CONTAINER" ASB_ROLLBACK_WORKER_CONTAINER="$PREV_WORKER_CONTAINER" \
    ASB_ROLLBACK_API_ID="$PREV_API_ID" ASB_ROLLBACK_WORKER_ID="$PREV_WORKER_ID" \
    ASB_ROLLBACK_API_HASH="$PREV_API_HASH" ASB_ROLLBACK_WORKER_HASH="$PREV_WORKER_HASH" \
    bash "$ROOT_DIR/scripts/deploy.sh" --env-file "$ROLLBACK_ENV_FILE" "${flags[@]}" "$1"
}

check_previous_environment() {
  local binding format='{{.Image}} {{index .Config.Labels "com.docker.compose.config-hash"}}'
  if [[ "$ROLLBACK_ENV_FILE" != /* ]]; then
    ROLLBACK_ENV_FILE="$ROOT_DIR/$ROLLBACK_ENV_FILE"
  fi
  if [ ! -f "$ROLLBACK_ENV_FILE" ] || [ "$ENV_FILE" -ef "$ROLLBACK_ENV_FILE" ] ||
    [ -z "$PREV_API_CONTAINER" ] || [ -z "$PREV_WORKER_CONTAINER" ]; then
    log_error "Rollback requires a separate previous env file and a running API and worker"
    return 1
  fi
  binding="$(docker inspect --format "$format" "$PREV_API_CONTAINER")" || return 1
  read -r PREV_API_ID PREV_API_HASH <<< "$binding"
  binding="$(docker inspect --format "$format" "$PREV_WORKER_CONTAINER")" || return 1
  read -r PREV_WORKER_ID PREV_WORKER_HASH <<< "$binding"
  ROLLBACK_ENV_SHA="$(rollback_env_sha "$ROLLBACK_ENV_FILE")" || return 1
  run_previous_environment _verify_previous_environment
}

verify_previous_service() {
  local mode="$1" role="$2" expected_id="$3" expected_container="$4"
  local expected_hash="$5"
  local image image_id config_hash
  [[ "$expected_id" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  config_hash="$(compose config --hash "$role" 2>/dev/null)" || return 1
  [[ "$expected_hash" =~ ^[a-f0-9]{64}$ ]] && [ "$config_hash" = "$role $expected_hash" ] || return 1
  if [ "$mode" = _verify_previous_environment ]; then
    image="$(compose config --images "$role" 2>/dev/null)" || return 1
    [[ -n "$image" && "$image" != *$'\n'* ]] || return 1
    image_id="$(docker image inspect --format '{{.Id}}' "$image" 2>/dev/null)" || return 1
    [ "$image_id" = "$expected_id" ] || return 1
    [ "$(compose ps -q "$role" 2>/dev/null | head -1)" = "$expected_container" ] || return 1
    service_containers_match "$role" "$expected_id" "$expected_hash" || return 1
  fi
}

verify_previous_environment() {
  local mode="$1" actual_sha
  actual_sha="$(rollback_env_sha "$ENV_FILE")" || return 1
  if [ -z "${ASB_ROLLBACK_ENV_SHA:-}" ] || [ "$actual_sha" != "$ASB_ROLLBACK_ENV_SHA" ]; then
    log_error "Previous environment file changed or its verification is unavailable"
    return 1
  fi
  check_requirements
  require_production_url || return 1
  if [ "$PROD_API_URL" != "${ASB_ROLLBACK_PROD_API_URL:-}" ]; then
    log_error "Previous environment does not use the deployment HTTPS origin"
    return 1
  fi
  if ! verify_previous_service "$mode" api "${ASB_ROLLBACK_API_ID:-}" \
      "${ASB_ROLLBACK_API_CONTAINER:-}" "${ASB_ROLLBACK_API_HASH:-}" ||
    ! verify_previous_service "$mode" worker "${ASB_ROLLBACK_WORKER_ID:-}" \
      "${ASB_ROLLBACK_WORKER_CONTAINER:-}" "${ASB_ROLLBACK_WORKER_HASH:-}"; then
    log_error "Previous Compose configuration does not match the expected API and worker"
    return 1
  fi
  if [ "$mode" = _restore_previous_environment ]; then
    PREV_API_ID="$ASB_ROLLBACK_API_ID" PREV_WORKER_ID="$ASB_ROLLBACK_WORKER_ID" restore_previous_images
  fi
}

rollback() {
  log_error "Deployment start or health check failed — attempting rollback"
  if [ -n "$ROLLBACK_ENV_FILE" ]; then
    if run_previous_environment _restore_previous_environment; then
      log_warn "Rollback restored the previous runtime settings and health"
      return 0
    fi
    log_error "Rollback with the previous runtime settings failed — manual intervention required"
  elif [ -n "$PREV_API_ID" ] && [ -n "$PREV_WORKER_ID" ]; then
    log_warn "Rolling back to the captured API and worker image IDs"
    if (restore_previous_images); then
      log_warn "Rollback restored health — investigate the failed release before retrying"
      return 0
    fi
    log_error "Rollback could not restore the expected images and health — manual intervention required"
  else
    log_error "No previous images captured — manual rollback required (check 'compose ps')"
  fi
  return 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --compose-file)
      if [ "$CUSTOM_COMPOSE_FILES" = true ]; then
        COMPOSE_FILES+=("$2")
      else
        COMPOSE_FILES=("$2")
        CUSTOM_COMPOSE_FILES=true
      fi
      shift 2
      ;;
    --rollback-env-file)
      ROLLBACK_ENV_FILE="$2"
      shift 2
      ;;
    --rollback-compose-file)
      if [ -z "${2:-}" ]; then
        log_error "--rollback-compose-file requires a path"
        exit 1
      fi
      ROLLBACK_COMPOSE_FILES+=("$2")
      shift 2
      ;;
    --image-tag)
      IMAGE_TAG_OVERRIDE="$2"
      shift 2
      ;;
    --help|-h)
      print_help
      exit 0
      ;;
    *)
      break
      ;;
  esac
done

COMMAND="${1:-}"
if [ -z "$COMMAND" ]; then
  print_help
  exit 1
fi
if [ -n "$ROLLBACK_ENV_FILE" ] && [ "$COMMAND" != deploy ]; then
  log_error "--rollback-env-file is only supported by deploy"
  exit 1
fi
if [ -n "${ROLLBACK_COMPOSE_FILES[0]:-}" ] && [ -z "$ROLLBACK_ENV_FILE" ]; then
  log_error "--rollback-compose-file requires --rollback-env-file"
  exit 1
fi

case "$COMMAND" in
  deploy)
    # M26: migrate-before-up. 구 스택을 내리지 않고(다운타임 없음) 새 이미지를 pull한 뒤
    # 마이그레이션을 먼저 적용(구 코드가 새 스키마와 잠깐 공존 — expand-then-contract 전제),
    # 그다음 서비스를 롤링 재기동. health 실패 시 이전 이미지로 자동 롤백.
    check_requirements
    require_production_url
    check_free_beta_release
    capture_running_images
    if [ -n "$ROLLBACK_ENV_FILE" ]; then
      check_previous_environment
    fi
    pull_images
    run_migrations
    if start_services && health_check; then
      log_info "Deployment completed successfully!"
    else
      if rollback; then
        log_error "Release rolled back. Deployment marked failed."
      fi
      exit 1
    fi
    ;;
  _verify_previous_environment|_restore_previous_environment)
    verify_previous_environment "$COMMAND"
    ;;
  start)
    check_requirements
    check_free_beta_release
    start_services
    ;;
  stop)
    check_requirements
    stop_services
    ;;
  restart)
    check_requirements
    restart_services
    ;;
  logs)
    check_requirements
    show_logs
    ;;
  status)
    check_requirements
    show_status
    ;;
  health)
    check_requirements
    health_check
    ;;
  migrate)
    check_requirements
    run_migrations
    ;;
  build)
    check_requirements
    pull_images
    ;;
  cleanup)
    cleanup
    ;;
  backup)
    check_requirements
    backup_db
    ;;
  smoke)
    check_requirements
    require_production_url
    "$ROOT_DIR/scripts/smoke.sh" "$PROD_API_URL"
    ;;
  *)
    print_help
    exit 1
    ;;
esac
