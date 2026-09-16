.PHONY: dev api web test test-api build generate migrate sync

api:
	cd api && .venv/bin/python run.py

web:
	cd frontend && npm run dev

# run both; Ctrl-C stops both
dev:
	@trap 'kill 0' INT TERM; \
	(cd api && .venv/bin/python run.py) & \
	(cd frontend && npm run dev) & \
	wait

test-api:
	cd api && .venv/bin/python -m pytest -q tests

test: test-api
	cd frontend && npx tsc -b --noEmit

build:
	cd frontend && npm run build

# usage: make generate URL=https://github.com/owner/repo [TAGS=3]
generate:
	cd api && .venv/bin/python -m app.cli generate $(URL) --tags $(or $(TAGS),3)

# usage: make migrate DB=postgres://...
migrate:
	cd api && .venv/bin/python -m app.cli migrate --db "$(DB)"

# usage: make sync DB=postgres://... [REPO=owner/name]
sync:
	cd api && .venv/bin/python -m app.cli sync-to "$(DB)" $(if $(REPO),--repo $(REPO),)
