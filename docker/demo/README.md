# locx demo in Docker

Runs the locx demo (Streamlit, `app/v2.py`) and its knowledge graph (Apache Jena Fuseki 6.2.0) on any
machine with Docker. It needs no GPU and no network access to the GPU server. The extraction pipeline
itself (vLLM, Gemma 4) is not included; the graph is the finished result of run `gemma4-31b_20261117-0709`.

## What you need

- Docker with Compose v2 (Docker Desktop on macOS/Windows, or Docker Engine on Linux)
- about 10 GB free disk (images ~1 GB, bundle 0.23 GB, database ~6 GB) and 6 GB RAM for Docker
- the bundle `locx_demo.tar.gz`

## Run it

```bash
tar xzf locx_demo.tar.gz
cd locx_demo
docker compose up --build
```

- **First start:** Fuseki loads the 10 named graphs listed in `graphs.tsv` (about 16 million triples) into its database and checks
  the triple counts. This takes a few minutes (about 2 on the GPU server), after which the log says
  `loaded and checked`.
  The demo container starts once Fuseki is ready. Later starts take seconds.
- Open **http://localhost:8501** for the demo.
- Fuseki's own query page is at http://localhost:3030 (read-only; dataset `locx`).
- The first visit to Home and Explore takes a few seconds (the all-assertions table is fetched once,
  then cached).

Stop with `Ctrl-C` or `docker compose down`. The database stays in the Docker volume `locx-demo_fuseki-db`.
To start from scratch, for example after an interrupted first load: `docker compose down -v`.

## Troubleshooting

| Problem | Fix |
|---|---|
| Port 8501 or 3030 in use | change the left number in `ports:` in `compose.yaml`, e.g. `"127.0.0.1:8601:8501"` |
| Fuseki stops during the first load (out of memory) | give Docker more memory, or `FUSEKI_JVM_ARGS=-Xmx2g docker compose up` |
| "holds an unfinished load" | `docker compose down -v`, then `docker compose up` |
| "loaded counts differ from graphs.tsv" | the export is incomplete; copy the bundle again |

## What is inside

| Path | What |
|---|---|
| `compose.yaml` | two services: `fuseki` and `demo`; both ports bound to localhost only |
| `docker/demo/Dockerfile.fuseki` | Fuseki 6.2.0 on Java 21 (release tarball checked by sha256) |
| `docker/demo/fuseki-config.ttl` | read-only dataset: `/locx/sparql`, `/locx/query`, `/locx/get`; no update endpoints |
| `docker/demo/fuseki-entrypoint.sh` | first start: load + count check; admin endpoints locked with a random password |
| `docker/demo/Dockerfile.app` | Python 3.11 + Streamlit with the demo's code, SPARQL queries and `reports/` |
| `data/demo_export/` | the graphs as gzipped N-Quads, one file per graph, and `graphs.tsv` (graph, file, triples) |

## Making a new bundle (on the server)

```bash
make demo-export   # reads the graphs from the server's Fuseki (read-only) -> data/demo_export/
make demo-bundle   # -> data/demo_bundle/locx_demo.tar.gz
```

Re-run both after the graphs change (new run, `make verdicts`, …).
