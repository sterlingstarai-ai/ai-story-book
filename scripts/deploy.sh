#!/bin/bash
set -e

# =====================================================
# AI Story Book - Deployment Script
# =====================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_NAME="ai-story-book"
COMPOSE_FILE="infra/docker-compose.prod.yml"
ENV_FILE=".env"

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_requirements() {
    log_info "Checking requirements..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed"
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose is not installed"
        exit 1
    fi

    if [ ! -f "$ENV_FILE" ]; then
        log_error "Environment file ($ENV_FILE) not found"
        log_info "Copy .env.example to .env and configure it"
        exit 1
    fi

    log_info "All requirements met"
}

build_images() {
    log_info "Building Docker images..."
    docker-compose -f $COMPOSE_FILE build --no-cache
    log_info "Images built successfully"
}

run_migrations() {
    log_info "Running database migrations..."
    docker-compose -f $COMPOSE_FILE run --rm api alembic upgrade head
    log_info "Migrations completed"
}

start_services() {
    log_info "Starting services..."
    docker-compose -f $COMPOSE_FILE up -d
    log_info "Services started"
}

stop_services() {
    log_info "Stopping services..."
    docker-compose -f $COMPOSE_FILE down
    log_info "Services stopped"
}

restart_services() {
    log_info "Restarting services..."
    docker-compose -f $COMPOSE_FILE restart
    log_info "Services restarted"
}

show_logs() {
    docker-compose -f $COMPOSE_FILE logs -f
}

show_status() {
    log_info "Service status:"
    docker-compose -f $COMPOSE_FILE ps
}

cleanup() {
    log_info "Cleaning up unused Docker resources..."
    docker system prune -f
    docker volume prune -f
    log_info "Cleanup completed"
}

backup_db() {
    log_info "Backing up database..."
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="backup_${TIMESTAMP}.sql"

    docker-compose -f $COMPOSE_FILE exec -T postgres pg_dump -U $DB_USER $DB_NAME > $BACKUP_FILE
    log_info "Database backed up to $BACKUP_FILE"
}

health_check() {
    log_info "Running health checks..."

    # Check API
    if curl -s -o /dev/null -w "%{http_code}" http://localhost/health | grep -q "200"; then
        log_info "API: Healthy"
    else
        log_error "API: Unhealthy"
    fi

    # Check services
    docker-compose -f $COMPOSE_FILE ps --format "table {{.Name}}\t{{.Status}}"
}

# Main
case "$1" in
    deploy)
        check_requirements
        build_images
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
        stop_services
        ;;
    restart)
        restart_services
        ;;
    logs)
        show_logs
        ;;
    status)
        show_status
        ;;
    health)
        health_check
        ;;
    migrate)
        run_migrations
        ;;
    build)
        build_images
        ;;
    cleanup)
        cleanup
        ;;
    backup)
        backup_db
        ;;
    *)
        echo "Usage: $0 {deploy|start|stop|restart|logs|status|health|migrate|build|cleanup|backup}"
        echo ""
        echo "Commands:"
        echo "  deploy   - Full deployment (build, start, migrate)"
        echo "  start    - Start all services"
        echo "  stop     - Stop all services"
        echo "  restart  - Restart all services"
        echo "  logs     - Show service logs"
        echo "  status   - Show service status"
        echo "  health   - Run health checks"
        echo "  migrate  - Run database migrations"
        echo "  build    - Build Docker images"
        echo "  cleanup  - Clean up unused Docker resources"
        echo "  backup   - Backup database"
        exit 1
        ;;
esac
