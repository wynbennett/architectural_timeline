.PHONY: dev api web test test-api build

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
