# Convenience commands. Run `make help` to list them.

.PHONY: help up down logs build ps migrate revision shell test

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

up:        ## Start the whole stack (builds if needed)
	docker compose up -d --build

down:      ## Stop the stack
	docker compose down

logs:      ## Tail backend logs
	docker compose logs -f backend

ps:        ## Show running services
	docker compose ps

build:     ## Rebuild the backend image
	docker compose build backend

migrate:   ## Apply DB migrations inside the backend container
	docker compose exec backend alembic upgrade head

revision:  ## Autogenerate a migration. Usage: make revision m="add users"
	docker compose exec backend alembic revision --autogenerate -m "$(m)"

shell:     ## Open a shell in the backend container
	docker compose exec backend /bin/sh

test:      ## Run the test suite
	docker compose exec backend pytest
