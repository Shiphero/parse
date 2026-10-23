.PHONY: setup up down logs status restart-worker

setup:
	python3 scripts/setup.py

up: setup
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs --tail=100 -f api worker web

status:
	docker compose ps

restart-worker:
	docker compose restart worker

.PHONY: check
check:
	docker compose exec -T web npm run build
	docker compose exec -T web npm test
	docker compose exec -T api python -m unittest discover -s /app/tests -v
	python3 -m unittest discover -s scripts/tests -v
	git diff --check

.PHONY: check-production
check-production:
	docker build --target production -t parse-production:local .
	python3 scripts/smoke_production.py
