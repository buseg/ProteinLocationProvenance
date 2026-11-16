# One target per milestone (SPEC §9). No Docker on this server (docs/DECISIONS.md).
SHELL := /bin/bash
MM    ?= $(HOME)/.local/bin/micromamba
GPU   := $(shell sed -n 's/^ *gpu: *\([0-9]*\).*/\1/p' config.yaml)

.PHONY: env kg fuseki-build fuseki-up fuseki-down fuseki-status fuseki-smoke fuseki-backup vllm-env serve serve-stop serve-smoke

## M0 — pipeline env (micromamba, conda-forge only)
env:
	if $(MM) env list | awk '{print $$1}' | grep -qx locx; then $(MM) update -y -n locx --override-channels -f env.yml; \
	else $(MM) create -y -n locx --override-channels -f env.yml; fi

## M0b — Fuseki (Java distribution)
fuseki-build:  ; ./scripts/fuseki.sh build
fuseki-up:     ; ./scripts/fuseki.sh up
fuseki-down:   ; ./scripts/fuseki.sh down
fuseki-status: ; ./scripts/fuseki.sh status
fuseki-smoke:  ; ./scripts/fuseki_smoke.sh
fuseki-backup:
	set -a; . ./.env; set +a; curl -sS -K- -X POST 'http://localhost:3030/$$/backup/locx' <<< "user = \"admin:$$FUSEKI_ADMIN_PASSWORD\""; echo

## M1 — vLLM (pip, env "vllm", GPU from config.yaml)
vllm-env: ; ./scripts/setup_vllm_env.sh
serve:    ; GPU=$(GPU) ./scripts/serve_vllm.sh start
serve-stop: ; ./scripts/serve_vllm.sh stop
serve-smoke: ; ./scripts/serve_vllm.sh smoke

## M2 — reference graphs (GO CC, GOA human, UniProt human) -> Fuseki
PY := $(MM) run -n locx python
kg: ; $(PY) -m locx.kg.build $(ARGS)
