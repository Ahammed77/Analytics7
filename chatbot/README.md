# Analytics 7 chatbot (MVP prototype)

A standalone chat box. A utility user types a question about their CIS data in plain English. The answer comes back as a table of rows plus one sentence. Follow-ups build on earlier turns. Suggested questions show as chips. Anything that is not a question about the CIS data gets a fixed reply.

Spec and tickets: `../../.scratch/analytics7-chatbot/` (outside this repo). Throwaway demo quality, no hardening.

## How a question moves

```
chat page ──► POST /api/messages ──► orchestrator (plain code, fixed order)
                                        1. ask      query model ◄── catalogue view + earlier turns + question   (never rows)
                                                    returns ONE structured query, or off_topic
                                        2. compile  text-to-SQL engine: every name checked against the catalogue,
                                                    values bound as parameters, row limit added
                                        3. run      read-only executor (read-only role, READ ONLY transaction,
                                                    statement timeout) ──► Postgres reporting DB; rows return to the app only
                                        4. phrase   template sentence (ticket 10 / X-1 pending)
                                     ──► one request-log line (no rows)
```

| Piece | File |
|---|---|
| Semantic catalogue (from the Cube YAMLs in `../cube/model/cubes` plus `config/catalogue_overlay.yml`) | `a7chat/catalogue.py`, `catalogue/catalogue.json` |
| Structured query format | `a7chat/structured_query.py` (format documented at the top) |
| Engine / executor | `a7chat/engine.py`, `a7chat/executor.py` |
| Query model, prompt check | `a7chat/query_model.py` |
| Orchestrator, API, chat page | `a7chat/orchestrator.py`, `a7chat/api.py`, `a7chat/static/index.html` |
| Approved questions and expected results (also the chips) | `config/approved_questions.yml` (provisional, pending Q1) |
| Fixed reply wording (placeholder, pending Rele) | `config/fixed_reply.txt` |
| Demo dataset | `db/` and `PROVENANCE.md` |

## Run it with Docker (FR-12)

Prerequisite: Docker Desktop.

1. `cd chatbot`
2. `docker compose up --build`
3. Open http://localhost:8000

The app calls the real query model (Claude, allowed on the fake demo data only), so set `ANTHROPIC_API_KEY` first:

```bash
ANTHROPIC_API_KEY=... docker compose up --build
```

For an offline backup, use `A7_QUERY_MODEL=recorded`. It replays the structured queries in `config/approved_questions.yml`, so only the approved questions and chips get answers. Every other question gets the fixed reply.

Request logs are written to `chatbot/logs/requests.jsonl`.

> The Docker path was written without Docker available on the build machine, so it has not been run yet. Run it once on a presenter machine before relying on it.

## Run it without Docker

Requires Python 3.11 or later. `pgserver` bundles Postgres, so nothing else needs installing.

```bash
cd chatbot
python -m venv .venv && .venv/Scripts/activate      # Windows; use .venv/bin/activate elsewhere
pip install -r requirements-dev.txt
python dev_server.py                                 # http://127.0.0.1:8000 (set ANTHROPIC_API_KEY, or A7_QUERY_MODEL=recorded)
```

On Windows, keep the venv on a short path (for example `C:\a7v`). Some packages fail to install under long paths.

## Tests

```bash
cd chatbot
pytest                                   # behaviour tests at the message-endpoint seam, against real Postgres
python -m mypy a7chat --ignore-missing-imports
```

The tests replace the query model with recorded structured queries (the deterministic fake). They assert on what comes back (rows, sentence, fixed reply), on the request log and on the prompt check.

## Approved-question runner (FR-9, ticket 09)

```bash
python -m a7chat.approved_runner --model claude --dsn postgresql://a7_reader:a7_reader@localhost:5433/a7_reporting
python -m a7chat.approved_runner --model recorded ...      # engine + data only, no model
python -m a7chat.approved_runner --model claude --checkpoint "13 Nov 2026 engine checkpoint"
```

The runner prints PASS or FAIL per question and keeps each run in `runs/` (the results plus that run's request log, for the privacy review). It also lists regressions against the previous run. `--checkpoint` appends the result and the engine decision to `docs/checkpoints.md`.

## Catalogue

```bash
python -m a7chat.catalogue generate      # after any Cube YAML or overlay change
python -m a7chat.catalogue check --dsn <admin or reader DSN>   # schema check + run every member on the DB
```

The Cube YAMLs are written for MS SQL. The generator translates `dateadd/datediff` truncation, `IIF` and `DATEPART` into Postgres. Members it cannot translate are kept and reported as unresolved: today these are the two `accountName` members that reference another cube. `keyAccount` is in scope but has no YAML yet, so it is reported as missing.

## Known gaps and open decisions

- **Ticket 10 (formatter)** is not built. It waits on Vincent's X-1 decision, so the sentence is a fixed template that reports the row count.
- **Q1**: the approved question set is provisional.
- **Q5**: the query model and its host are open. The code calls Claude (`A7_CLAUDE_MODEL`, default `claude-opus-5-5`, server-side refusal fallback on) for the demo only. The product path must be self-hosted in-region (NFR-9).
- **Prompt contract**: the query model receives today's date as well as the question, catalogue and earlier turns, so it can resolve relative dates ("last year"). This is an addition to the spec's contract and needs confirming (Kyi). The prompt check allows it.
- **Query model errors** (no key, network, rate limit) give a clear "couldn't reach the query model" message. Nothing runs, and the request is logged with outcome `model_error`.
- **Guardrail with the real model**: the tests prove that an off-topic signal leads to the fixed reply with no SQL. Whether the real model flags weather, instruction overrides and "delete all accounts" is only shown by a real-model runner run. Writes are also blocked by the SELECT-only check and the read-only role. If a real model maps an unanswerable question onto real members, nothing but that run catches it.
- **Customer class**: comes from the overlay, with the CIS column `cust_class` assumed. It needs confirming.
- **Stories 10 and 11** (consumption by cycle or route, comparing billing periods) need cubes outside the subset.
- **Real-model results**: the approved-question run against the real model has not been done (there was no API key on the build machine). Only the recorded run has passed.
- The Cube YAML for `cashBatchData` marks two primary keys. The chatbot does not use primary keys, so this has no effect here.
