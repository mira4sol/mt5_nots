.PHONY: help install install-dev install-prod install-native install-bridge install-linux install-charts setup \
        test test-whatsapp test-mt5 test-mt5-mock test-openclaw-hook test-whatsapp-inbound test-commands diagnose-whatsapp \
        dev prod run health send-chart run-chart \
        deploy deploy-prereqs pm2-start pm2-stop pm2-logs pm2-status install-openclaw-hook

# Prefer venv python when present
VENV      ?= .venv
PYTHON    ?= $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)
PIP       ?= $(if $(wildcard $(VENV)/bin/pip),$(VENV)/bin/pip,pip3)
GIT_REMOTE ?= origin
PM2_CONFIG ?= pm2.config.js

# Load .env for make targets if present
ifneq (,$(wildcard .env))
  include .env
  export
endif
HEALTH_PORT ?= 8080
HEALTH_HOST ?= 127.0.0.1
TEST_OPENCLAW_HOME ?= $(CURDIR)/data/test-openclaw

help:
	@echo "MT5 Trigger Monitor"
	@echo ""
	@echo "Setup:"
	@echo "  make setup          Create venv, install deps + charts, copy config templates"
	@echo "  make install-dev    Install with mock+bridge (Mac/Linux dev)"
	@echo "  make install-native Install with native MT5 (Windows)"
	@echo "  make install-bridge Install with bridge support (Mac/Linux)"
	@echo "  make install-linux  Install with mt5linux (Linux VPS)"
	@echo ""
	@echo "Tests:"
	@echo "  make test                  Run WhatsApp + MT5 + OpenClaw hook tests"
	@echo "  make test-whatsapp         Send test message via OpenClaw"
	@echo "  make test-mt5              Connect to MT5 and list open positions"
	@echo "  make test-mt5-mock         MT5 test using mock backend (no terminal)"
	@echo "  make test-openclaw-hook    Install hook to data/test-openclaw (isolated)"
	@echo "  make test-whatsapp-inbound POST /guide to webhook (requires make prod)"
	@echo "  make test-commands         test-openclaw-hook + test-whatsapp-inbound"
	@echo ""
	@echo "Charts:"
	@echo "  make install-charts        Install mplfinance/matplotlib for chart scripts"
	@echo "  make send-chart            Live XAUUSD chart → WhatsApp group (alias: run-chart)"
	@echo ""
	@echo "Run:"
	@echo "  make dev            Start monitor with MT5_BACKEND=mock"
	@echo "  make prod           Start monitor (uses .env / accounts.yaml)"
	@echo "  make run            Alias for prod"
	@echo "  make health         Curl local /health endpoint"
	@echo "  make install-openclaw-hook  Wire WhatsApp group commands via OpenClaw"
	@echo "  make diagnose-whatsapp       Check OpenClaw + webhook wiring"
	@echo ""
	@echo "Deploy (VPS):"
	@echo "  make deploy         git pull, install deps, restart PM2"
	@echo "  make pm2-start      Start/restart app via pm2.config.js"
	@echo "  make pm2-stop       Stop mt5-trigger in PM2"
	@echo "  make pm2-logs       Tail PM2 logs"
	@echo "  make pm2-status     Show PM2 process status"

# --- Setup ---

$(VENV)/bin/activate:
	python3 -m venv $(VENV)

setup: $(VENV)/bin/activate install-charts
	$(PIP) install -e ".[dev]"
	@test -f .env || cp .env.example .env
	@test -f config/accounts.yaml || cp config/accounts.yaml.example config/accounts.yaml
	@mkdir -p data
	@echo "Setup complete. Edit .env and config/accounts.yaml, then: make test"

install: install-prod

install-dev: $(VENV)/bin/activate
	$(PIP) install -e ".[dev]"

install-prod: $(VENV)/bin/activate
	$(PIP) install -e .
	@echo "Installed mt5linux in venv (required for Linux bridge)"

install-native: $(VENV)/bin/activate
	$(PIP) install -e ".[native]"

install-bridge: $(VENV)/bin/activate
	$(PIP) install -e ".[bridge]"

install-linux: $(VENV)/bin/activate
	$(PIP) install -e ".[linux]"

install-charts: $(VENV)/bin/activate
	$(PIP) install -e ".[charts]"

# --- Tests ---

test: test-whatsapp test-mt5 test-openclaw-hook

test-whatsapp:
	$(PYTHON) scripts/test_whatsapp.py

test-mt5: install-prod
	@$(PYTHON) -c "import mt5linux" 2>/dev/null || ( \
		echo "ERROR: mt5linux not installed in venv. Run: make install-prod" >&2; \
		echo "  Or: $(PIP) install mt5linux" >&2; \
		exit 1)
	$(PYTHON) scripts/test_mt5.py --pending

test-mt5-mock:
	$(PYTHON) scripts/test_mt5.py --backend mock --pending

test-openclaw-hook:
	@mkdir -p data
	@echo "Installing OpenClaw hook to isolated $(TEST_OPENCLAW_HOME)..."
	OPENCLAW_HOME="$(TEST_OPENCLAW_HOME)" $(PYTHON) scripts/install_openclaw_hook.py
	@test -e "$(TEST_OPENCLAW_HOME)/hooks/mt5-whatsapp-commands/HOOK.md"
	@test -e "$(TEST_OPENCLAW_HOME)/hooks/mt5-whatsapp-commands/handler.ts"
	@test -e "$(TEST_OPENCLAW_HOME)/plugins/mt5-whatsapp-commands/index.ts"
	@test -f "$(TEST_OPENCLAW_HOME)/openclaw.json" || test -f "$(TEST_OPENCLAW_HOME)/config.json"
	@python3 -c "import json, pathlib; p=pathlib.Path('$(TEST_OPENCLAW_HOME)/openclaw.json'); c=json.loads(p.read_text()); assert c['channels']['whatsapp']['pluginHooks']['messageReceived'] is True; assert c['plugins']['entries']['mt5-whatsapp-commands']['enabled'] is True; assert c['plugins']['entries']['mt5-whatsapp-commands']['config']['accountsByGroup']"
	@echo "OpenClaw hook install test OK ($(TEST_OPENCLAW_HOME))"

test-whatsapp-inbound:
	@echo "Posting /guide to local webhook (requires: make prod)..."
	$(PYTHON) scripts/whatsapp_inbound_hook.py

test-commands: test-openclaw-hook test-whatsapp-inbound

# --- Run ---

dev:
	MT5_BACKEND=mock $(PYTHON) -m mt5_trigger

prod run:
	$(PYTHON) -m mt5_trigger

health:
	@curl -sf http://$(HEALTH_HOST):$(HEALTH_PORT)/health | python3 -m json.tool || \
		(echo "Health endpoint not reachable at http://$(HEALTH_HOST):$(HEALTH_PORT)/health (make prod?)" && exit 1)

install-openclaw-hook:
	$(PYTHON) scripts/install_openclaw_hook.py

diagnose-whatsapp:
	$(PYTHON) scripts/diagnose_whatsapp_commands.py

send-chart run-chart: install-charts install-prod
	$(PYTHON) scripts/send_chart.py

# --- Deploy (VPS) ---

deploy-prereqs:
	@test -f .env || (echo "ERROR: .env missing. Run: cp .env.example .env && edit credentials" >&2; exit 1)
	@test -f config/accounts.yaml || cp config/accounts.yaml.example config/accounts.yaml
	@mkdir -p data
	@command -v pm2 >/dev/null 2>&1 || (echo "ERROR: pm2 not found. Install: npm install -g pm2" >&2; exit 1)

deploy: $(VENV)/bin/activate deploy-prereqs
	@echo "==> Pulling latest from $(GIT_REMOTE)..."
	@git pull --ff-only $(GIT_REMOTE) || (echo "ERROR: git pull failed (merge conflict or no network?)" >&2; exit 1)
	@echo "==> Installing/updating Python dependencies..."
	@$(MAKE) install-prod
	@echo "==> Installing OpenClaw WhatsApp command hook..."
	@$(MAKE) install-openclaw-hook || echo "WARN: OpenClaw hook install skipped (openclaw missing or .env incomplete)"
	@echo "==> Restarting PM2 ($(PM2_CONFIG))..."
	@pm2 startOrRestart $(PM2_CONFIG)
	@pm2 save 2>/dev/null || true
	@echo "==> Deploy complete."
	@pm2 status mt5-trigger || pm2 status
	@echo "Check health: make health"

pm2-start: deploy-prereqs install-prod
	@pm2 startOrRestart $(PM2_CONFIG)
	@pm2 save 2>/dev/null || true

pm2-stop:
	@pm2 stop mt5-trigger 2>/dev/null || pm2 delete mt5-trigger 2>/dev/null || true

pm2-logs:
	@pm2 logs mt5-trigger

pm2-status:
	@pm2 status mt5-trigger || pm2 status
