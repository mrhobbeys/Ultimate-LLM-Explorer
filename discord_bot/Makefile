.PHONY: install install-dev test run stress hwinfo lint clean

VENV ?= .venv
PY := $(VENV)/bin/python

install:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -U pip
	$(VENV)/bin/pip install -r requirements.txt

install-dev: install
	$(VENV)/bin/pip install pytest ruff

test:
	$(PY) -m pytest tests/ -q

run:
	$(PY) -m bot

stress:
	$(PY) scripts/stress.py --seconds 15

hwinfo:
	$(PY) -m bot.hwinfo

lint:
	$(VENV)/bin/ruff check bot/ || true

clean:
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(VENV)
