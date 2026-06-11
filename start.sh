#!/bin/bash

# Color codes for clean output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}       Starting PinBot Services          ${NC}"
echo -e "${GREEN}=========================================${NC}"

# 1. Check for Virtual Environment
if [ ! -d ".venv" ]; then
    echo -e "${RED}Error: Virtual environment (.venv) not found.${NC}"
    echo -e "Please create it and install dependencies first:"
    echo -e "  python -m venv .venv"
    echo -e "  source .venv/bin/activate"
    echo -e "  pip install -e \".[dev]\""
    exit 1
fi

# 2. Check and start Redis
REDIS_STARTED_BY_SCRIPT=false
if ! redis-cli ping >/dev/null 2>&1; then
    echo -e "${YELLOW}Redis is not running. Attempting to start local redis-server...${NC}"
    if command -v redis-server >/dev/null 2>&1; then
        redis-server --daemonize yes
        sleep 1.5
        if redis-cli ping >/dev/null 2>&1; then
            echo -e "${GREEN}Local Redis server started successfully.${NC}"
            REDIS_STARTED_BY_SCRIPT=true
        else
            echo -e "${RED}Error: Failed to start Redis server automatically.${NC}"
            echo -e "Please start Redis manually (e.g., sudo systemctl start redis)."
            exit 1
        fi
    else
        echo -e "${RED}Error: redis-server command not found.${NC}"
        echo -e "Please install Redis on your system (e.g., sudo pacman -S redis or sudo apt install redis-server)."
        exit 1
    fi
else
    echo -e "${GREEN}Redis is already running.${NC}"
fi

# 3. Setup cleanup trap to kill child processes when script exits (or on Ctrl+C)
cleanup() {
    echo -e "\n${YELLOW}Stopping all services...${NC}"
    
    # Terminate celery and uvicorn background processes
    if [ -n "$CELERY_PID" ] && kill -0 $CELERY_PID 2>/dev/null; then
        echo -e "Stopping Celery worker..."
        kill -TERM $CELERY_PID 2>/dev/null
    fi
    if [ -n "$UVICORN_PID" ] && kill -0 $UVICORN_PID 2>/dev/null; then
        echo -e "Stopping FastAPI server..."
        kill -TERM $UVICORN_PID 2>/dev/null
    fi

    # Terminate local redis if we started it
    if [ "$REDIS_STARTED_BY_SCRIPT" = true ]; then
        echo -e "${YELLOW}Stopping local Redis server...${NC}"
        redis-cli shutdown 2>/dev/null
    fi
    
    echo -e "${GREEN}All services stopped successfully.${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# 4. Start Celery Worker (with Beat scheduler enabled via -B)
echo -e "${GREEN}Starting Celery worker (with Beat scheduler)...${NC}"
./.venv/bin/celery -A app.workers.celery_app worker -B --loglevel=info &
CELERY_PID=$!

# Wait a brief moment to let Celery initialize and avoid log interleaving at start
sleep 2

# 5. Start FastAPI / Uvicorn Server
echo -e "${GREEN}Starting FastAPI Web Server...${NC}"
./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload &
UVICORN_PID=$!

echo -e "${GREEN}All services started! Press Ctrl+C to stop all of them.${NC}"

# Keep running and wait for background processes
wait $CELERY_PID $UVICORN_PID
