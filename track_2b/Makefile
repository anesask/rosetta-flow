.PHONY: help run build lock clean test lint format
.DEFAULT_GOAL := help

# Git Bash/MSYS make starts recipes with a stripped Windows environment; the Docker CLI needs
# ProgramFiles (plugin dir for compose/buildx) and USERPROFILE (config, context) to work.
# USERPROFILE comes from the registry because PowerShell may run in constrained language mode.
ifneq ($(shell command -v cygpath 2>/dev/null),)
export ProgramFiles ?= C:\Program Files
export USERPROFILE ?= $(shell reg.exe query "HKCU\Volatile Environment" 2>/dev/null | sed -n 's/^ *USERPROFILE *REG_SZ *//p' | tr -d '\r')
DOCKER := docker.exe
HOSTDIR := $(shell cygpath -m "$(CURDIR)")
else
DOCKER := docker
HOSTDIR := $(CURDIR)
endif

# https://no-color.org
ifeq ($(NO_COLOR),)
ESC  := $(shell printf '\033')
BOLD := $(ESC)[1m
DIM  := $(ESC)[2m
CYAN := $(ESC)[36m
GRN  := $(ESC)[32m
RST  := $(ESC)[0m
endif
STEP = @printf '$(CYAN)==>$(RST) $(BOLD)%s$(RST) $(DIM)%s$(RST)\n'
DONE = @printf '$(GRN)%s$(RST)\n'

help: ## Show available targets
	@printf '$(BOLD)rosetta-flow$(RST) $(DIM)make targets$(RST)\n'
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  $(CYAN)%-8s$(RST) %s\n", $$1, $$2}'

run: build ## Build the image and start the web app on http://localhost:8000 (needs LLM_* env vars or .env)
	$(STEP) "Running" "open http://localhost:8000, stop with Ctrl+C"
	@$(DOCKER) compose --progress quiet run --rm --service-ports rosetta-flow

build: ## Build the Docker image
	$(STEP) "Building image" "(first build takes a few minutes)"
	@$(DOCKER) compose build
	$(DONE) "image ready"

# Resolves inside the runtime base image so pins match the platform that installs them.
# MSYS_NO_PATHCONV stops Git Bash from rewriting the container-side paths.
lock: ## Regenerate pinned requirements.txt from pyproject.toml
	$(STEP) "Locking dependencies" "(python:3.13-slim, extra: app)"
	@MSYS_NO_PATHCONV=1 $(DOCKER) run --rm -v "$(HOSTDIR):/w:ro" python:3.13-slim sh -c '\
		cp -r /w/pyproject.toml /w/src /tmp/ && cd /tmp && \
		pip install -q --root-user-action=ignore --disable-pip-version-check ".[app]" && \
		echo "# Pinned runtime dependencies for the Docker image (linux, python 3.13)." && \
		echo "# Generated from pyproject.toml [app] with: make lock" && \
		pip freeze --exclude rosetta-flow' > requirements.txt.tmp && mv requirements.txt.tmp requirements.txt
	$(DONE) "requirements.txt updated"

clean: ## Remove leftover untagged images from earlier builds of this project
	$(STEP) "Removing old images" ""
	@$(DOCKER) image prune -f --filter label=com.docker.compose.project=track_2b

test: ## Run unit tests (local, no network)
	python -m pytest -q

lint: ## Check style with ruff (optional, pip install -e ".[dev]")
	ruff check src
	ruff format --check src

format: ## Auto-fix and format with ruff (optional)
	ruff check --fix src
	ruff format src
