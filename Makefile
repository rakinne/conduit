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

PY         ?= python3
MOCK_VENV  ?= .venv-mock
MOCK_PY     = $(MOCK_VENV)/bin/python
FACEFORMER ?= $(HOME)/Downloads/FaceFormer-main

.DEFAULT_GOAL := help
.PHONY: help test test-frontend test-all mock-venv mock serve

help:
	@echo "conduit dev harness:"
	@echo "  make test           brain unit tests        (no deps)"
	@echo "  make test-frontend  frontend routing logic  (needs node)"
	@echo "  make test-all       all of the above"
	@echo "  make mock-venv      create minimal numpy+scipy venv ($(MOCK_VENV))"
	@echo "  make mock           run speak_server --mock"
	@echo "  make serve          run real server (FACEFORMER=/path/to/clone)"

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
	$(PY) tools/speak_server.py --faceformer $(FACEFORMER)
