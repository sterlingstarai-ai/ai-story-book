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
  deploy   Pull images, restart services, run migrations, run health checks
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
  log_info "Cleaning up unused Docker resources..."
  docker system prune -f
  docker volume prune -f
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

health_check() {
  log_info "Running health checks..."
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
    check_requirements
    pull_images
    stop_services
    start_services
    run_migrations
    health_check
    log_info "Deployment completed successfully!"
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
