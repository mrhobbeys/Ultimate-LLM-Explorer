.PHONY: install backend frontend dev test lint clean

install:
	cd backend && pip install -e ".[dev]"
	cd frontend && npm install

backend:
	cd backend && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev

dev:
	@echo "Starting backend and frontend..."
	@(cd backend && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000) & \
	(cd frontend && npm run dev) & \
	wait

test:
	cd backend && pytest

lint:
	cd backend && ruff check app tests && mypy app

clean:
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/.mypy_cache
	rm -rf frontend/dist frontend/.vite
	find . -name "__pycache__" -type d -exec rm -rf {} +
