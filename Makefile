# One target per milestone (SPEC §9). No Docker on this server (docs/DECISIONS.md).
SHELL := /bin/bash
MM    ?= $(HOME)/.local/bin/micromamba
GPU   := $(shell sed -n 's/^ *gpu: *\([0-9]*\).*/\1/p' config.yaml)

.PHONY: env kg corpus candidates fuseki-build fuseki-up fuseki-down fuseki-status fuseki-smoke fuseki-backup vllm-env serve serve-stop serve-smoke serve2 serve2-stop serve2-smoke extract-dev extract validate rdf load verdicts silver-eval precision-sample precision report demo demo-stop demo-check demo-export demo-bundle abstracts schema

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
GPU2  := $(shell sed -n 's/^ *second_gpu: *\([0-9]*\).*/\1/p' config.yaml)
serve2:       ; GPU=$(GPU2) PORT=8001 ./scripts/serve_vllm.sh start
serve2-stop:  ; PORT=8001 ./scripts/serve_vllm.sh stop
serve2-smoke: ; PORT=8001 ./scripts/serve_vllm.sh smoke

## M2 — reference graphs (GO CC, GOA human, UniProt human) -> Fuseki
PY := $(MM) run -n locx python -u
kg: ; $(PY) -m locx.kg.build $(ARGS)

## M3 — corpus tiers + Europe PMC metadata + PubTator text/genes
corpus: ; $(PY) -m locx.corpus

## M4 — sentences, protein + location candidates, prefilter
candidates: ; $(PY) -m locx.extract.candidates $(ARGS)

## M5 — extraction (vLLM must be up: make serve)
extract-dev: ; $(PY) -m locx.extract.run --tiers dev $(ARGS) && $(PY) -m locx.extract.samples
extract:     ; $(PY) -m locx.extract.run --tiers silver,discovery $(ARGS)

## M6 — validation (Python part; V5/V6 are SHACL shapes in M7)
validate: ; $(PY) -m locx.extract.validate $(ARGS)

## M7 — claims to RDF + SHACL (quality flags, gate), then load into Fuseki
rdf:  ; $(PY) -m locx.kg.claims_rdf build $(ARGS)
load: ; $(PY) -m locx.kg.claims_rdf load $(ARGS)
abstracts: ; $(PY) -m locx.kg.abstracts_rdf build && $(PY) -m locx.kg.abstracts_rdf load   # text for the demo's abstract view

## M8 — verdicts against GOA + aggregation (author groups, counts)
verdicts: ; $(PY) -m locx.analysis.verdicts $(ARGS)

## M9 — evaluation (silver recall, precision sheet)
silver-eval: ; $(PY) -m locx.analysis.silver_eval $(ARGS)
precision-sample: ; $(PY) -m locx.analysis.precision sample $(ARGS)
precision:        ; $(PY) -m locx.analysis.precision score

## M10 — report numbers + figures
report: ; $(PY) -m locx.analysis.report $(ARGS)
schema: ; $(PY) scripts/kg_schema.py && $(PY) scripts/kg_schema_fig.py   # KG classes/fields -> reports/kg_schema.*, fig_kg_*

## M11 — Streamlit demo on 127.0.0.1:8501 (laptop: ssh -L 8502:localhost:8501 ...)
demo:       ; ./scripts/demo.sh start
demo-stop:  ; ./scripts/demo.sh stop
demo-check: ; $(PY) app/check_demo.py
demo-export: ; $(PY) scripts/demo_export.py      # graphs -> data/demo_export (for Docker, docker/demo/README.md)
demo-bundle: ; ./scripts/demo_bundle.sh           # one tar.gz with code + export for another machine
