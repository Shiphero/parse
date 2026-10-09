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
