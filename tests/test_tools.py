"""Unit tests for dvt_agent.tools.

Each builder is a pure function — tests assert it produces dicts that match
the YAML shape DVT expects (cross-referenced against the citibike samples in
the upstream repo's docs/examples.md).
"""

from __future__ import annotations

import yaml

from dvt_agent import tools


# --- column validation -------------------------------------------------------

def test_column_validation_count_only():
    result = tools.build_column_validation(
        source_table="bigquery-public-data.new_york_citibike.citibike_stations",
        target_table="my-project.staging.citibike_stations",
        aggregates=["count"],
    )
    assert result["status"] == "success"
    v = result["validation"]
    assert v["type"] == "Column"
    assert v["schema_name"] == "bigquery-public-data.new_york_citibike"
    assert v["table_name"] == "citibike_stations"
    assert v["target_schema_name"] == "my-project.staging"
    assert v["target_table_name"] == "citibike_stations"
    assert v["aggregates"] == [
        {"field_alias": "count", "source_column": None, "target_column": None, "type": "count"}
    ]
    assert v["threshold"] == 0.0


def test_column_validation_sum_with_grouping_and_filter():
    result = tools.build_column_validation(
        source_table="p.d.t",
        target_table="p.d.t",
        aggregates=["sum:amount", "avg:price"],
        grouped_columns=["region_id"],
        filters=["region_id = 71"],
        threshold=0.01,
    )
    assert result["status"] == "success"
    v = result["validation"]
    assert v["aggregates"][0] == {
        "field_alias": "sum__amount",
        "source_column": "amount",
        "target_column": "amount",
        "type": "sum",
    }
    assert v["aggregates"][1]["type"] == "avg"
    assert v["grouped_columns"] == [
        {"cast": None, "field_alias": "region_id",
         "source_column": "region_id", "target_column": "region_id"}
    ]
    assert v["filters"] == [{"source": "region_id = 71", "target": "region_id = 71", "type": "custom"}]
    assert v["threshold"] == 0.01


def test_column_validation_rejects_bad_table_format():
    result = tools.build_column_validation(
        source_table="just_a_table",
        target_table="p.d.t",
        aggregates=["count"],
    )
    assert result["status"] == "error"
    assert "project.dataset.table" in result["error"]


def test_column_validation_rejects_unknown_aggregate():
    result = tools.build_column_validation(
        source_table="p.d.t",
        target_table="p.d.t",
        aggregates=["median:price"],
    )
    assert result["status"] == "error"


def test_column_validation_rejects_aggregate_missing_column():
    result = tools.build_column_validation(
        source_table="p.d.t",
        target_table="p.d.t",
        aggregates=["sum"],
    )
    assert result["status"] == "error"
    assert "requires a column" in result["error"]


# --- row validation ----------------------------------------------------------

def test_row_validation_with_comparison_fields():
    result = tools.build_row_validation(
        source_table="p.d.orders",
        target_table="p.d.orders",
        primary_keys=["order_id"],
        comparison_fields=["status", "total"],
    )
    assert result["status"] == "success"
    v = result["validation"]
    assert v["type"] == "Row"
    assert v["primary_keys"][0]["source_column"] == "order_id"
    assert {f["source_column"] for f in v["comparison_fields"]} == {"status", "total"}
    assert "hash" not in v


def test_row_validation_hash_all():
    result = tools.build_row_validation(
        source_table="p.d.orders",
        target_table="p.d.orders",
        primary_keys=["order_id"],
        hash_all=True,
    )
    assert result["status"] == "success"
    v = result["validation"]
    assert v["hash"] == "*"
    assert "comparison_fields" not in v


def test_row_validation_random_rows_with_batch():
    result = tools.build_row_validation(
        source_table="p.d.orders",
        target_table="p.d.orders",
        primary_keys=["order_id"],
        hash_all=True,
        random_rows=True,
        batch_size=100,
    )
    assert result["status"] == "success"
    v = result["validation"]
    assert v["use_random_rows"] is True
    assert v["random_row_batch_size"] == "100"


def test_row_validation_requires_primary_keys():
    result = tools.build_row_validation(
        source_table="p.d.orders",
        target_table="p.d.orders",
        primary_keys=[],
        hash_all=True,
    )
    assert result["status"] == "error"


def test_row_validation_rejects_hash_and_fields_together():
    result = tools.build_row_validation(
        source_table="p.d.orders",
        target_table="p.d.orders",
        primary_keys=["id"],
        hash_all=True,
        comparison_fields=["x"],
    )
    assert result["status"] == "error"


def test_row_validation_requires_one_of_hash_or_fields():
    result = tools.build_row_validation(
        source_table="p.d.orders",
        target_table="p.d.orders",
        primary_keys=["id"],
    )
    assert result["status"] == "error"


# --- schema validation -------------------------------------------------------

def test_schema_validation_basic():
    result = tools.build_schema_validation(
        source_table="a.b.users",
        target_table="x.y.users",
    )
    assert result["status"] == "success"
    v = result["validation"]
    assert v == {
        "type": "Schema",
        "schema_name": "a.b",
        "table_name": "users",
        "target_schema_name": "x.y",
        "target_table_name": "users",
        "format": "table",
    }


def test_schema_validation_with_exclusions():
    result = tools.build_schema_validation(
        source_table="a.b.t", target_table="a.b.t",
        exclusion_columns=["created_at", "updated_at"],
    )
    assert result["validation"]["exclusion_columns"] == ["created_at", "updated_at"]


# --- custom query ------------------------------------------------------------

def test_custom_query_column():
    result = tools.build_custom_query_validation(
        query_type="column",
        source_query="SELECT COUNT(*) AS c FROM p.d.t",
        target_query="SELECT COUNT(*) AS c FROM p.d.t2",
    )
    assert result["status"] == "success"
    v = result["validation"]
    assert v["type"] == "Custom-query"
    assert v["validation_type"] == "Column"


def test_custom_query_row_requires_pk():
    result = tools.build_custom_query_validation(
        query_type="row",
        source_query="SELECT * FROM p.d.t",
        target_query="SELECT * FROM p.d.t",
    )
    assert result["status"] == "error"


def test_custom_query_row_with_pk():
    result = tools.build_custom_query_validation(
        query_type="row",
        source_query="SELECT id, name FROM p.d.t",
        target_query="SELECT id, name FROM p.d.t",
        primary_keys=["id"],
    )
    assert result["status"] == "success"
    assert result["validation"]["validation_type"] == "Row"
    assert result["validation"]["primary_keys"][0]["source_column"] == "id"


# --- write_config / list_configs / read_config -------------------------------

def test_write_then_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "CONFIGS_DIR", tmp_path)

    col = tools.build_column_validation(
        source_table="p.d.t", target_table="p.d.t", aggregates=["count"],
    )["validation"]

    written = tools.write_config(
        config_name="test_count",
        source_conn="bq_conn",
        target_conn="bq_conn",
        validations=[col],
    )
    assert written["status"] == "success"
    assert written["path"].endswith("test_count.yaml")
    assert "data-validation configs run -c" in written["run_command"]

    listed = tools.list_configs()
    assert "test_count" in listed["configs"]

    readback = tools.read_config("test_count")
    assert readback["status"] == "success"
    assert readback["contents"]["source"] == "bq_conn"
    assert readback["contents"]["target"] == "bq_conn"
    assert readback["contents"]["validations"][0]["type"] == "Column"
    assert "result_handler" not in readback["contents"]


def test_write_with_result_handler(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "CONFIGS_DIR", tmp_path)

    col = tools.build_column_validation(
        source_table="p.d.t", target_table="p.d.t", aggregates=["count"],
    )["validation"]

    tools.write_config(
        config_name="with_handler",
        source_conn="bq",
        target_conn="bq",
        validations=[col],
        result_handler={
            "type": "BigQuery",
            "project_id": "my-proj",
            "table_id": "pso_data_validator.results",
        },
    )

    on_disk = yaml.safe_load((tmp_path / "with_handler.yaml").read_text())
    assert on_disk["result_handler"]["table_id"] == "pso_data_validator.results"
    # Ordering matters for human readability: result_handler should come first.
    assert list(on_disk.keys())[0] == "result_handler"


def test_write_rejects_bad_name(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "CONFIGS_DIR", tmp_path)
    result = tools.write_config(
        config_name="bad name with spaces",
        source_conn="bq", target_conn="bq",
        validations=[{"type": "Schema"}],
    )
    assert result["status"] == "error"


def test_write_rejects_empty_validations(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "CONFIGS_DIR", tmp_path)
    result = tools.write_config(
        config_name="ok", source_conn="bq", target_conn="bq", validations=[],
    )
    assert result["status"] == "error"


def test_read_missing_config(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "CONFIGS_DIR", tmp_path)
    result = tools.read_config("does_not_exist")
    assert result["status"] == "error"
