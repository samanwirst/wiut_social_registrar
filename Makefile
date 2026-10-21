PYTHON ?= python
NPM ?= npm

.PHONY: check lint format frontend test browser docker-test postgres-test

check: lint frontend test

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

frontend:
	$(NPM) run build --prefix frontend

test:
	$(PYTHON) -m pytest -q

postgres-test:
	$(PYTHON) scripts/test_postgres.py

browser: frontend
	$(PYTHON) tests/browser_miniapp.py

docker-test:
	docker build --target test -t wiut-social-registrar:test .
