.PHONY: setup dev turbo test backup health logs stop clean

setup:
	cp -n .env.example .env || true
	docker compose build
	docker compose up -d postgres redis
	@echo "Waiting for services..."
	sleep 3
	docker compose up -d backend frontend
	@echo "Setup complete. Dashboard: http://localhost:3000  API: http://localhost:8000/docs"

dev:
	docker compose up --build

turbo:
	docker compose exec backend python -c \
		"import httpx; httpx.post('http://localhost:8000/api/v1/generate-farm', json={'mode':'TURBO','count':10000})"

test:
	docker compose exec backend pytest -v --cov=. --cov-report=term-missing

backup:
	docker compose run --rm db-backup

health:
	@curl -s http://localhost:8000/health | python3 -m json.tool

logs:
	docker compose logs -f --tail=100 backend

stop:
	docker compose down
	@echo "All services stopped."

clean:
	docker compose down -v --remove-orphans
	@echo "Volumes and containers removed."
