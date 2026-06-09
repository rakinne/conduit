# conduit — repeatable dev/test harness for the speech + LLM-brain backend.
#
# The page (index.html) and the macOS shell are GUI and run on a real machine;
# this Makefile covers the tools/speak_server.py backend so the /ask loop can be
# run and tested on ANY machine, with or without the heavy FaceFormer stack.
#
#   make test           brain unit tests        (no deps)
#   make test-frontend  frontend routing logic  (needs node, no deps)
#   make test-all       all of the above
#   make mock-venv      one-time: minimal numpy+scipy venv for --mock
#   make mock           run speak_server in mock mode (no FaceFormer/torch/Ollama)
#   make serve          run the real server (FACEFORMER=/path/to/clone)
#   make trace-ui       launch the LOCAL Phoenix trace UI (needs arize-phoenix)
#
# Local conversation tracing (opt-in, never leaves the machine — see decision #16):
# install tools/requirements-phoenix.txt, run `make trace-ui` in one shell, then
# prefix mock/serve with CONDUIT_TRACE=1, e.g. `CONDUIT_TRACE=1 make mock`.

PY         ?= python3
MOCK_VENV  ?= .venv-mock
MOCK_PY     = $(MOCK_VENV)/bin/python
FACEFORMER ?= $(HOME)/Downloads/FaceFormer-main
# The REAL server needs the FaceFormer deps (torch etc.), which live in a
# Python 3.10 conda env, not system python3. Auto-detect a `faceformer` conda
# env; override with FF_PY=/path/to/python if yours lives elsewhere.
FF_PY      ?= $(firstword $(wildcard $(HOME)/miniconda3/envs/faceformer/bin/python $(HOME)/anaconda3/envs/faceformer/bin/python) $(PY))

.DEFAULT_GOAL := help
.PHONY: help test test-frontend test-all mock-venv mock serve trace-ui trace-deps

help:
	@echo "conduit dev harness:"
	@echo "  make test           brain unit tests        (no deps)"
	@echo "  make test-frontend  frontend routing logic  (needs node)"
	@echo "  make test-all       all of the above"
	@echo "  make mock-venv      create minimal numpy+scipy venv ($(MOCK_VENV))"
	@echo "  make mock           run speak_server --mock"
	@echo "  make serve          run real server (FACEFORMER=/path/to/clone)"
	@echo "  make trace-ui       launch LOCAL Phoenix trace UI (needs arize-phoenix)"
	@echo "  make trace-deps     install the trace client into the mock venv"
	@echo "  (tracing: 'make trace-deps' once, run 'make trace-ui' in another shell,"
	@echo "   then 'make mock' — the repo .env sets CONDUIT_TRACE=1. Local only, no cloud)"

test:
	$(PY) tools/test_speak_ask.py

test-frontend:
	node tools/test_frontend.mjs

test-all: test test-frontend

mock-venv:
	$(PY) -m venv $(MOCK_VENV)
	$(MOCK_PY) -m pip install -q -U pip
	$(MOCK_PY) -m pip install -q -r tools/requirements-mock.txt
	@echo "mock venv ready: $(MOCK_PY)"

mock:
	@test -x $(MOCK_PY) || { echo "no mock venv — run 'make mock-venv' first"; exit 1; }
	$(MOCK_PY) tools/speak_server.py --mock

serve:
	@echo "using FF_PY=$(FF_PY)  (override with FF_PY=... if wrong)"
	$(FF_PY) tools/speak_server.py --faceformer $(FACEFORMER)

# Local-only trace UI (Arize Phoenix). Stores traces on-disk; nothing leaves the
# machine. The UI needs the FULL `arize-phoenix` in TRACE_PY's env (system python
# usually has it); the server only needs the light client (see trace-deps).
TRACE_PY ?= $(PY)
trace-ui:
	@echo "starting LOCAL Phoenix trace UI on http://localhost:6006 (Ctrl-C to stop)"
	@echo "needs arize-phoenix in $(TRACE_PY) — 'pip install arize-phoenix' if missing"
	$(TRACE_PY) -m phoenix.server.main serve

# Install the lightweight trace CLIENT into the mock venv so `make mock` can emit
# spans (the faceformer env for `make serve` usually already has phoenix).
trace-deps:
	@test -x $(MOCK_PY) || { echo "no mock venv — run 'make mock-venv' first"; exit 1; }
	$(MOCK_PY) -m pip install -q -U pip
	$(MOCK_PY) -m pip install -q -r tools/requirements-phoenix.txt
	@echo "trace client installed into $(MOCK_PY)"
