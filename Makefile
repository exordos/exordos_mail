SHELL := bash
SSH_KEY ?= ~/.ssh/id_ed25519.pub

.PHONY: build

all: help

help:
	@echo "build            - build the mailaas element manifest + DP image"
	@echo "wheel            - build the exordos_mail Python wheel"
	@echo "lint             - run ruff check"
	@echo "format           - run ruff format"
	@echo "test             - run unit tests via tox"
	@echo "functional       - run functional tests (needs a live core with mailaas)"
	@echo "typecheck        - run mypy"

build:
	# A linked worktree's Git metadata is unavailable inside the build VM.
	@if test -f .git; then bash exordos/images/build_wheel.sh; fi
	exordos build -c exordos/exordos.yaml -i $(SSH_KEY) -f "$(CURDIR)"

wheel:
	tox -e wheel

lint:
	tox -e ruff-check

format:
	tox -e ruff

test:
	tox -e py312

functional:
	tox -e py312-functional

typecheck:
	tox -e mypy
