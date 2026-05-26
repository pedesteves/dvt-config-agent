# DVT Config Builder Agent

A Google ADK agent that turns natural-language requests into YAML config files
for the [professional-services-data-validator (DVT)](https://github.com/GoogleCloudPlatform/professional-services-data-validator).

The agent generates configs only — you run them yourself with
`data-validation configs run -c <path>`.

## Scope

Supported source → target pairings:
- **BigQuery → BigQuery**
- **Teradata → BigQuery**

Validation types: `Column`, `Row`, `Schema`, `Custom-query`.

Table identifiers depend on engine:
- BigQuery: `project.dataset.table`
- Teradata: `database.table`

Connections must already be registered via
`data-validation connections add` — the agent references them by name and
will not invent or create them.

### Row validations always use explicit columns

The agent never emits `hash: '*'` — DVT's YAML loader doesn't expand the
wildcard at config-load time (only the CLI does that lookup), so a stored
config containing `hash: '*'` crashes at runtime with
`TypeError: reduce() of empty iterable with no initial value`.

If you ask to "hash all columns" or "compare all columns" the agent will
ask for the explicit list and emit one of:
- `hash: "col1,col2,..."` (default — single SHA-256 equality check), or
- `comparison_fields:` (per-column mismatch reporting) when you ask for it.

Note: If you plan to perform row level hashing on Teradata, you might need to install a UDF that implements sha256 on your Teradata instance as some versions don't support it. 

## Install

Requires Python 3.11+.

```bash
cd /home/agent (change to where the agent is installed)
pip install -e .
cp .env.example .env
# edit .env to add a real GOOGLE_API_KEY (or Vertex AI vars)
```

`google-adk` is pinned to `2.0.0b1` which is currently Beta.


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

- *Row-compare `my-project.ds.orders` against `my-project-tgt.ds.orders`,
  primary key `order_id`, hashing `status` and `total`, conn `bq_conn`.*
  → produces a Row validation with `hash: "status,total"`. Ask for
  `comparison_fields` instead if you want per-column mismatch reporting.

- *Validate the schema matches between `project_a.ds.users` and `project_b.ds.users`.*
  → produces a Schema validation.

- *Compare row counts between Teradata `sales_db.orders` (conn `td_conn`)
  and BigQuery `my-proj.warehouse.orders` (conn `bq_conn`).*
  → produces a Column validation with a `count` aggregate, source schema
  `sales_db`, target schema `my-proj.warehouse`.

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
