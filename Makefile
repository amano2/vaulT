.PHONY: dev test lint eval inspect doctor serve-stdio serve-http install

PYTHON ?= python

install:
	$(PYTHON) -m pip install -e .

dev:
	$(PYTHON) -m server.vaultmcp.main console --vault ./fixtures/test_vault

test:
	$(PYTHON) -m pytest server/tests -v

lint:
	$(PYTHON) -m ruff check server/ || true

eval:
	$(PYTHON) eval/conformance_runner.py
	$(PYTHON) eval/tool_use_eval.py

doctor:
	$(PYTHON) -m server.vaultmcp.main doctor --vault ./fixtures/test_vault

serve-stdio:
	$(PYTHON) -m server.vaultmcp.main --stdio --vault ./fixtures/test_vault

serve-http:
	$(PYTHON) -m server.vaultmcp.main --http --port 8765 --vault ./fixtures/test_vault

inspect:
	npx @modelcontextprotocol/inspector $(PYTHON) -m server.vaultmcp.main --stdio --vault ./fixtures/test_vault
