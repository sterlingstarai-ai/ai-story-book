#!/bin/bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="infra/docker-compose.prod.yml"
ENV_FILE=""
IMAGE_TAG_OVERRIDE=""
COMPOSE_CMD=()
PREV_API_IMAGE=""
PREV_WORKER_IMAGE=""

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
Usage: ./scripts/deploy.sh [--env-file PATH] [--compose-file PATH] [--image-tag TAG] <command>

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
  backup   Backup database
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
  if [ -f "$ROOT_DIR/.env" ]; then
    ENV_FILE=".env"
  fi
}

load_env_file() {
  if [ -z "$ENV_FILE" ]; then
    log_error "No environment file found. Use --env-file or create infra/.env"
    exit 1
  fi
  if [ ! -f "$ROOT_DIR/$ENV_FILE" ]; then
    log_error "Environment file ($ENV_FILE) not found"
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/$ENV_FILE"
  set +a
}

compose() {
  (
    cd "$ROOT_DIR"
    "${COMPOSE_CMD[@]}" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
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

  export API_IMAGE="${API_IMAGE:-ghcr.io/${repo_path}/api:${IMAGE_TAG_OVERRIDE}}"
  export WORKER_IMAGE="${WORKER_IMAGE:-ghcr.io/${repo_path}/worker:${IMAGE_TAG_OVERRIDE}}"
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
  log_info "Using compose file: $COMPOSE_FILE"
}

pull_images() {
  log_info "Pulling configured images..."
  compose pull
  log_info "Images pulled successfully"
}

run_migrations() {
  log_info "Running database migrations..."
  compose run --rm api alembic upgrade head
  log_info "Migrations completed"
}

start_services() {
  log_info "Starting services..."
  compose up -d
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
  log_info "Backing up database..."
  local timestamp backup_file
  timestamp="$(date +%Y%m%d_%H%M%S)"
  backup_file="$ROOT_DIR/backup_${timestamp}.sql"
  compose exec -T postgres pg_dump -U "$DB_USER" "$DB_NAME" >"$backup_file"
  log_info "Database backed up to $backup_file"
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
    if curl -fsS http://localhost/health/live >/dev/null 2>&1; then
      log_info "Service is live (attempt $attempt)"
      return 0
    fi
    sleep "$HEALTH_WAIT_INTERVAL"
    attempt=$((attempt + 1))
  done
  log_error "Service did not become live within $((HEALTH_WAIT_RETRIES * HEALTH_WAIT_INTERVAL))s"
  return 1
}

health_check() {
  log_info "Running health checks..."
  if ! wait_for_liveness; then
    return 1
  fi
  if curl -fsS http://localhost/health/live >/dev/null; then
    log_info "Liveness check passed"
  else
    log_error "Liveness check failed"
    return 1
  fi

  if curl -fsS http://localhost/health/ready >/dev/null; then
    log_info "Readiness check passed"
  else
    log_error "Readiness check failed"
    return 1
  fi

  compose ps --format "table {{.Name}}\t{{.Status}}"
}

capture_running_images() {
  # M26: 새 이미지를 올리기 전 현재 실행 중인 컨테이너의 이미지 태그를 저장(롤백 대상).
  local api_cid worker_cid
  api_cid="$(compose ps -q api 2>/dev/null | head -1 || true)"
  worker_cid="$(compose ps -q worker 2>/dev/null | head -1 || true)"
  if [ -n "$api_cid" ]; then
    PREV_API_IMAGE="$(docker inspect --format '{{.Config.Image}}' "$api_cid" 2>/dev/null || true)"
  fi
  if [ -n "$worker_cid" ]; then
    PREV_WORKER_IMAGE="$(docker inspect --format '{{.Config.Image}}' "$worker_cid" 2>/dev/null || true)"
  fi
  if [ -n "$PREV_API_IMAGE" ]; then
    log_info "Captured current images for rollback: api=$PREV_API_IMAGE"
  else
    log_warn "No running api container found — rollback unavailable (fresh deploy)"
  fi
}

rollback() {
  log_error "Deployment health check failed — attempting rollback"
  if [ -n "$PREV_API_IMAGE" ] && [ -n "$PREV_WORKER_IMAGE" ]; then
    log_warn "Rolling back to api=$PREV_API_IMAGE worker=$PREV_WORKER_IMAGE"
    API_IMAGE="$PREV_API_IMAGE" WORKER_IMAGE="$PREV_WORKER_IMAGE" compose up -d
    if health_check; then
      log_warn "Rollback restored health — investigate the failed release before retrying"
      return 0
    fi
    log_error "Rollback health check also failed — manual intervention required"
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
      COMPOSE_FILE="$2"
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

case "$COMMAND" in
  deploy)
    # M26: migrate-before-up. 구 스택을 내리지 않고(다운타임 없음) 새 이미지를 pull한 뒤
    # 마이그레이션을 먼저 적용(구 코드가 새 스키마와 잠깐 공존 — expand-then-contract 전제),
    # 그다음 서비스를 롤링 재기동. health 실패 시 이전 이미지로 자동 롤백.
    check_requirements
    capture_running_images
    pull_images
    run_migrations
    start_services
    if health_check; then
      log_info "Deployment completed successfully!"
    else
      if rollback; then
        log_error "Release rolled back to previous images. Deployment marked failed."
      fi
      exit 1
    fi
    ;;
  start)
    check_requirements
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
  *)
    print_help
    exit 1
    ;;
esac
