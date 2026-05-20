# DVT Config Builder Agent

A Google ADK agent that turns natural-language requests into YAML config files
for the [professional-services-data-validator (DVT)](https://github.com/GoogleCloudPlatform/professional-services-data-validator).

The agent generates configs only — you run them yourself with
`data-validation configs run -c <path>`.

## Scope (v0.1)

- **BigQuery only** for source and target.
- Validation types: `Column`, `Row`, `Schema`, `Custom-query`.
- Connections must already be registered via
  `data-validation connections add` — the agent references them by name and
  will not invent or create them.

## Install

Requires Python 3.11+.

```bash
cd /home/agent (change to where the agent is installed)
pip install -e .
cp .env.example .env
# edit .env to add a real GOOGLE_API_KEY (or Vertex AI vars)
```

`google-adk` is pinned to `2.0.0b1`. The 2.0 line is beta.


## Run

Interactive terminal:

```bash
adk run dvt_agent
```

Web UI (recommended for inspecting tool calls):

```bash
adk web --port 8000
# open http://localhost:8000 and pick `dvt_agent` from the dropdown
```

Both commands must be run from this directory (the parent of `dvt_agent/`).

## Example prompts

- *Compare row counts between `bigquery-public-data.new_york_citibike.citibike_stations`
  and `my-project.staging.citibike_stations` using connection `bq_conn` for both.*
  → produces a Column validation with a `count` aggregate.

- *Hash every column of `my-project.ds.orders` against `my-project-tgt.ds.orders`,
  primary key `order_id`, conn name `bq_conn`.*
  → produces a Row validation with `hash: '*'`.

- *Validate the schema matches between `project_a.ds.users` and `project_b.ds.users`.*
  → produces a Schema validation.

Generated YAML is written to `dvt_agent/configs/`. The agent replies with the
absolute path and the exact `data-validation configs run -c …` command to
execute it.

## Tests

```bash
pip install -e ".[dev]"
pytest tests/
```

## Layout

```
.
├── pyproject.toml          # google-adk==2.0.0b1, pyyaml
├── .env.example
├── dvt_agent/
│   ├── __init__.py         # `from . import agent`
│   ├── agent.py            # root_agent — what `adk run`/`adk web` looks for
│   ├── tools.py            # the function tools
│   └── configs/            # generated YAML lands here
└── tests/
    └── test_tools.py
```
