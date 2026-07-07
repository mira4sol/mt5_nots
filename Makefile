.PHONY: help install install-dev install-prod install-native install-bridge install-linux setup \
        test test-whatsapp test-mt5 test-mt5-mock dev prod run health

# Prefer venv python when present
VENV      ?= .venv
PYTHON    ?= $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)
PIP       ?= $(if $(wildcard $(VENV)/bin/pip),$(VENV)/bin/pip,pip3)

# Load .env for make targets if present
ifneq (,$(wildcard .env))
  include .env
  export
endif

help:
	@echo "MT5 Trigger Monitor"
	@echo ""
	@echo "Setup:"
	@echo "  make setup          Create venv, install deps, copy config templates"
	@echo "  make install-dev    Install with mock+bridge (Mac/Linux dev)"
	@echo "  make install-native Install with native MT5 (Windows)"
	@echo "  make install-bridge Install with bridge support (Mac/Linux)"
	@echo "  make install-linux  Install with mt5linux (Linux VPS)"
	@echo ""
	@echo "Tests:"
	@echo "  make test           Run WhatsApp + MT5 connection tests"
	@echo "  make test-whatsapp  Send test message via OpenClaw"
	@echo "  make test-mt5       Connect to MT5 and list open positions"
	@echo "  make test-mt5-mock  MT5 test using mock backend (no terminal)"
	@echo ""
	@echo "Run:"
	@echo "  make dev            Start monitor with MT5_BACKEND=mock"
	@echo "  make prod           Start monitor (uses .env / accounts.yaml)"
	@echo "  make run            Alias for prod"
	@echo "  make health         Curl local /health endpoint"

# --- Setup ---

$(VENV)/bin/activate:
	python3 -m venv $(VENV)

setup: $(VENV)/bin/activate
	$(PIP) install -e ".[dev]"
	@test -f .env || cp .env.example .env
	@test -f config/accounts.yaml || cp config/accounts.yaml.example config/accounts.yaml
	@mkdir -p data
	@echo "Setup complete. Edit .env and config/accounts.yaml, then: make test"

install: install-dev

install-dev: $(VENV)/bin/activate
	$(PIP) install -e ".[dev]"

install-prod: $(VENV)/bin/activate
	$(PIP) install -e .

install-native: $(VENV)/bin/activate
	$(PIP) install -e ".[native]"

install-bridge: $(VENV)/bin/activate
	$(PIP) install -e ".[bridge]"

install-linux: $(VENV)/bin/activate
	$(PIP) install -e ".[linux]"

# --- Tests ---

test: test-whatsapp test-mt5

test-whatsapp:
	$(PYTHON) scripts/test_whatsapp.py

test-mt5:
	$(PYTHON) scripts/test_mt5.py --pending

test-mt5-mock:
	$(PYTHON) scripts/test_mt5.py --backend mock --pending

# --- Run ---

dev:
	MT5_BACKEND=mock $(PYTHON) -m mt5_trigger

prod run:
	$(PYTHON) -m mt5_trigger

health:
	@curl -sf http://localhost:8080/health | python3 -m json.tool || \
		(echo "Health endpoint not reachable. Is the server running? (make prod)" && exit 1)
