# Copyright 2026 Robert H. Mowery III
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Loads the generated warehouse into BigQuery.

Usage:
    python -m tessaway.warehouse.load

The dataset is created by Terraform (``infra/``). This script replaces every
table in it with a fresh build from the fixed seed, so running it twice leaves
the same data. Tables get names and types only: no descriptions are set,
because the experiment gives agents a schema and nothing about meaning.
"""

from __future__ import annotations

import io
import json

from google.cloud import bigquery

from tessaway import config
from tessaway.warehouse import generate, query, schema


def load_table(client: bigquery.Client, name: str, rows: list[generate.Row]) -> int:
    """Replace one table with ``rows`` and return the row count BigQuery reports."""
    table_id = f"{config.project()}.{config.DATASET}.{name}"
    nullable = schema.NULLABLE.get(name, set())
    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField(col, kind, mode="NULLABLE" if col in nullable else "REQUIRED")
            for col, kind in schema.TABLES[name]
        ],
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    payload = io.BytesIO("\n".join(json.dumps(row) for row in rows).encode())
    client.load_table_from_file(payload, table_id, job_config=job_config).result()
    return int(client.get_table(table_id).num_rows or 0)


def main() -> None:
    """Generate the warehouse and load every table."""
    client = query.client()
    tables = generate.generate()
    for name, rows in tables.items():
        loaded = load_table(client, name, rows)
        if loaded != len(rows):
            raise SystemExit(f"{name}: generated {len(rows)} rows but BigQuery holds {loaded}")
        print(f"{name:18s} {loaded:>8,d} rows", flush=True)
    print(f"seed {generate.SEED}  fingerprint {generate.fingerprint(tables)}")


if __name__ == "__main__":
    main()
