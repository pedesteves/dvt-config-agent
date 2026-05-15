"""Function tools for the DVT config-builder agent.

Each tool returns a dict with a `status` key (`"success"` or `"error"`) so the
ADK runtime and the LLM can both reason about the outcome. Builders are pure
(no I/O); only `write_config`, `list_configs`, and `read_config` touch disk.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

CONFIGS_DIR = Path(__file__).parent / "configs"

_AGGREGATE_TYPES = {"count", "sum", "avg", "min", "max", "bit_xor"}
_TABLE_RE = re.compile(r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")
_CONFIG_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _split_table(qualified: str) -> tuple[str, str]:
    """Split `project.dataset.table` into (`project.dataset`, `table`).

    DVT's YAML uses `schema_name` for the dataset (with project prefix) and
    `table_name` for the bare table.
    """
    if not _TABLE_RE.match(qualified):
        raise ValueError(
            f"Expected fully-qualified BigQuery table 'project.dataset.table', got {qualified!r}"
        )
    project, dataset, table = qualified.split(".")
    return f"{project}.{dataset}", table


def _expand_aggregate(spec: str) -> dict[str, Any]:
    """Turn shorthand like `"count"` or `"sum:amount"` into a DVT aggregate dict."""
    if ":" in spec:
        agg_type, column = spec.split(":", 1)
    else:
        agg_type, column = spec, None
    agg_type = agg_type.strip().lower()
    if agg_type not in _AGGREGATE_TYPES:
        raise ValueError(
            f"Unknown aggregate type {agg_type!r}. Must be one of {sorted(_AGGREGATE_TYPES)}."
        )
    if agg_type == "count" and column is None:
        column = None  # null/null = count(*)
        alias = "count"
    elif column is None:
        raise ValueError(f"Aggregate {agg_type!r} requires a column, e.g. {agg_type}:price")
    else:
        column = column.strip()
        alias = f"{agg_type}__{column}"
    return {
        "field_alias": alias,
        "source_column": column,
        "target_column": column,
        "type": agg_type,
    }


def build_column_validation(
    source_table: str,
    target_table: str,
    aggregates: list[str],
    grouped_columns: list[str] | None = None,
    filters: list[str] | None = None,
    threshold: float = 0.0,
) -> dict[str, Any]:
    """Build a single Column-validation entry.

    Args:
        source_table: Fully-qualified source table, e.g. "my-project.dataset.orders".
        target_table: Fully-qualified target table.
        aggregates: List of shorthand specs. Each is either a bare aggregate
            ("count") or "<type>:<column>" (e.g. "sum:amount", "avg:price").
            Supported types: count, sum, avg, min, max, bit_xor.
        grouped_columns: Optional list of column names to group results by.
        filters: Optional list of SQL filter expressions (applied to both
            source and target). Example: "region_id = 71".
        threshold: Allowed percentage difference before a validation fails
            (0.0 = exact match required).

    Returns:
        A dict with `status` plus a `validation` key containing the DVT entry.
    """
    try:
        src_schema, src_table = _split_table(source_table)
        tgt_schema, tgt_table = _split_table(target_table)
        agg_dicts = [_expand_aggregate(a) for a in aggregates]
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}

    if not agg_dicts:
        return {"status": "error", "error": "At least one aggregate is required."}

    validation: dict[str, Any] = {
        "type": "Column",
        "schema_name": src_schema,
        "table_name": src_table,
        "target_schema_name": tgt_schema,
        "target_table_name": tgt_table,
        "aggregates": agg_dicts,
        "threshold": threshold,
        "format": "table",
        "use_random_rows": False,
    }
    if grouped_columns:
        validation["grouped_columns"] = [
            {
                "cast": None,
                "field_alias": col,
                "source_column": col,
                "target_column": col,
            }
            for col in grouped_columns
        ]
    if filters:
        validation["filters"] = [
            {"source": expr, "target": expr, "type": "custom"} for expr in filters
        ]

    return {"status": "success", "validation": validation}


def build_row_validation(
    source_table: str,
    target_table: str,
    primary_keys: list[str],
    comparison_fields: list[str] | None = None,
    hash_all: bool = False,
    random_rows: bool = False,
    batch_size: int | None = None,
    threshold: float = 0.0,
) -> dict[str, Any]:
    """Build a single Row-validation entry.

    Args:
        source_table: Fully-qualified source table.
        target_table: Fully-qualified target table.
        primary_keys: Column names that uniquely identify a row in both tables.
        comparison_fields: Specific columns to compare row-by-row. Mutually
            exclusive with hash_all.
        hash_all: If true, hash every column (DVT's `--hash '*'`). Use this
            when you want a full row-equality check without listing columns.
        random_rows: If true, sample random rows instead of comparing all.
        batch_size: Row count per random batch (only meaningful when
            random_rows=True).
        threshold: Allowed percentage of mismatched rows before failing.

    Returns:
        A dict with `status` plus a `validation` key containing the DVT entry.
    """
    if not primary_keys:
        return {"status": "error", "error": "primary_keys is required for row validation."}
    if hash_all and comparison_fields:
        return {
            "status": "error",
            "error": "Use either hash_all OR comparison_fields, not both.",
        }
    if not hash_all and not comparison_fields:
        return {
            "status": "error",
            "error": "Provide comparison_fields, or set hash_all=True to hash every column.",
        }

    try:
        src_schema, src_table = _split_table(source_table)
        tgt_schema, tgt_table = _split_table(target_table)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}

    validation: dict[str, Any] = {
        "type": "Row",
        "schema_name": src_schema,
        "table_name": src_table,
        "target_schema_name": tgt_schema,
        "target_table_name": tgt_table,
        "primary_keys": [
            {"cast": None, "field_alias": pk, "source_column": pk, "target_column": pk}
            for pk in primary_keys
        ],
        "threshold": threshold,
        "format": "table",
        "use_random_rows": random_rows,
    }
    if hash_all:
        validation["hash"] = "*"
    else:
        validation["comparison_fields"] = [
            {"cast": None, "field_alias": col, "source_column": col, "target_column": col}
            for col in comparison_fields  # type: ignore[union-attr]
        ]
    if random_rows and batch_size is not None:
        validation["random_row_batch_size"] = str(batch_size)

    return {"status": "success", "validation": validation}


def build_schema_validation(
    source_table: str,
    target_table: str,
    exclusion_columns: list[str] | None = None,
) -> dict[str, Any]:
    """Build a single Schema-validation entry.

    Compares column names and data types between source and target. Does not
    read any rows.

    Args:
        source_table: Fully-qualified source table.
        target_table: Fully-qualified target table.
        exclusion_columns: Column names to skip during comparison.

    Returns:
        A dict with `status` plus a `validation` key containing the DVT entry.
    """
    try:
        src_schema, src_table = _split_table(source_table)
        tgt_schema, tgt_table = _split_table(target_table)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}

    validation: dict[str, Any] = {
        "type": "Schema",
        "schema_name": src_schema,
        "table_name": src_table,
        "target_schema_name": tgt_schema,
        "target_table_name": tgt_table,
        "format": "table",
    }
    if exclusion_columns:
        validation["exclusion_columns"] = list(exclusion_columns)

    return {"status": "success", "validation": validation}


def build_custom_query_validation(
    query_type: str,
    source_query: str,
    target_query: str,
    primary_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Build a single Custom-query validation entry.

    Args:
        query_type: Either "column" (aggregate-style) or "row" (row-by-row).
        source_query: SQL run against the source connection.
        target_query: SQL run against the target connection.
        primary_keys: Required when query_type="row" — columns that uniquely
            identify a row in the result set.

    Returns:
        A dict with `status` plus a `validation` key containing the DVT entry.
    """
    qt = query_type.strip().lower()
    if qt not in {"column", "row"}:
        return {"status": "error", "error": "query_type must be 'column' or 'row'."}
    if qt == "row" and not primary_keys:
        return {"status": "error", "error": "primary_keys required for row-type custom queries."}

    validation: dict[str, Any] = {
        "type": "Custom-query",
        "validation_type": qt.capitalize(),
        "source_query": source_query,
        "target_query": target_query,
        "format": "table",
    }
    if primary_keys:
        validation["primary_keys"] = [
            {"cast": None, "field_alias": pk, "source_column": pk, "target_column": pk}
            for pk in primary_keys
        ]
    return {"status": "success", "validation": validation}


def write_config(
    config_name: str,
    source_conn: str,
    target_conn: str,
    validations: list[dict[str, Any]],
    result_handler: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize a complete DVT config to YAML on disk.

    Args:
        config_name: File basename (no extension). Letters, digits, _ and - only.
        source_conn: Name of a source connection the user has already
            registered via `data-validation connections add`.
        target_conn: Name of the target connection.
        validations: List of validation dicts (each from a build_* tool's
            `validation` key).
        result_handler: Optional `{"type": "BigQuery", "project_id": ...,
            "table_id": "dataset.table"}` to persist results.

    Returns:
        A dict with `status`, `path` (absolute YAML path), and `run_command`
        (exact CLI to execute it).
    """
    if not _CONFIG_NAME_RE.match(config_name):
        return {
            "status": "error",
            "error": "config_name must contain only letters, digits, underscores, and hyphens.",
        }
    if not validations:
        return {"status": "error", "error": "validations list is empty."}

    config: dict[str, Any] = {}
    if result_handler:
        config["result_handler"] = result_handler
    config["source"] = source_conn
    config["target"] = target_conn
    config["validations"] = validations

    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CONFIGS_DIR / f"{config_name}.yaml"
    with out_path.open("w") as fh:
        yaml.safe_dump(config, fh, sort_keys=False)

    abs_path = str(out_path.resolve())
    return {
        "status": "success",
        "path": abs_path,
        "run_command": f"data-validation configs run -c {abs_path}",
    }


def list_configs() -> dict[str, Any]:
    """List YAML configs previously generated by this agent."""
    if not CONFIGS_DIR.exists():
        return {"status": "success", "configs": []}
    names = sorted(p.stem for p in CONFIGS_DIR.glob("*.yaml"))
    return {"status": "success", "configs": names}


def read_config(config_name: str) -> dict[str, Any]:
    """Read a previously generated config and return its parsed contents."""
    if not _CONFIG_NAME_RE.match(config_name):
        return {"status": "error", "error": "Invalid config_name."}
    path = CONFIGS_DIR / f"{config_name}.yaml"
    if not path.exists():
        return {"status": "error", "error": f"No config named {config_name!r} found."}
    with path.open() as fh:
        contents = yaml.safe_load(fh)
    return {"status": "success", "path": str(path.resolve()), "contents": contents}
