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

"""Part 5's planted drift: billing reloads 2026 with Canadian amounts already converted.

The story, at the fictional Tessaway Freight: billing migrates to a new system
and reloads its 2026 history. The new system stores every amount in US dollars,
converted at the month's rate. Nobody tells the Controller, and ``curr_cd`` on
those rows still says ``CAD``. Same tables, same columns, same types, same row
counts. Every query still runs. The official ``currency`` definition says CAD
rows are stored unconverted and must be converted, so anything that follows it
(an agent, the semantic layer, the gold SQL) now converts them a second time.

Everything happens in a copy, never in the warehouse of record:

    python -m tessaway.drift copy    --dataset tessaway_wh_p5   # load a clean copy from the generator
    python -m tessaway.drift plant   --dataset tessaway_wh_p5   # the reload (restated history)
    python -m tessaway.drift plant   --dataset tessaway_wh_p5 --since 2026-10-01   # forward only
    python -m tessaway.drift revert  --dataset tessaway_wh_p5   # reload billing from the generator
    python -m tessaway.drift status  --dataset tessaway_wh_p5   # rows that differ from the record
    python -m tessaway.drift gold    --dataset tessaway_wh_p5   # the gold SQL's answers on the copy

The copy is built from ``tessaway.warehouse.generate`` (the fixed seed), the
same way ``tessaway.warehouse.load`` builds the warehouse, not from the files in
``data/generated``. ``gold`` runs the reviewed gold SQL against the copy for
measurement only: what the answer key would say if someone recomputed it. The
check never scores against it (see ``tessaway/golden_set.py``).

Which rate each amount is reloaded at, following the ``currency`` definition:
an invoice at its invoice month, a credit memo at its credit month, a canceled
load fee at its fee month, and every cost on an invoiced load (linehaul pay,
the carrier's fuel surcharge, accessorials) at the invoice month. A cost on a
load not yet invoiced goes at its own date's month (``pay_dt``, ``chrg_dt``)
or, with no date, at the snapshot month.
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from google.api_core import exceptions as gax
from google.cloud import bigquery

from tessaway import config, golden_set, questions, scoring
from tessaway.warehouse import generate, load, query, schema

RECORD = "tessaway_wh"  # the warehouse of record: never planted, never reverted
RESTATED_SINCE = date(2026, 1, 1)  # all of 2026: the history billing reloaded
SNAPSHOT_MONTH = generate.SNAPSHOT.date().replace(day=1)
FX = (
    "(SELECT eff_mo_dt, fx_rt FROM `{d}.ref_fx_rate`"
    " WHERE from_curr_cd = 'CAD' AND to_curr_cd = 'USD')"
)


@dataclass(frozen=True)
class Reload:
    """One billing table the reload rewrites."""

    table: str
    key: str
    amounts: tuple[str, ...]
    # SQL for the date whose month sets the rate; ``t`` is the table, ``i`` the load's invoice.
    rate_date: str
    needs_invoice: bool


RELOADS: tuple[Reload, ...] = (
    Reload("bil_cust_inv", "inv_id", ("inv_tot_amt",), "t.inv_dt", False),
    Reload("bil_cr_memo", "cr_memo_id", ("cr_amt",), "t.cr_dt", False),
    Reload("bil_canc_fee", "canc_fee_id", ("cust_fee_amt", "carr_fee_amt"), "t.fee_dt", False),
    Reload(
        "bil_carr_pay",
        "pay_id",
        ("lh_pay_amt",),
        f"COALESCE(i.inv_dt, t.pay_dt, DATE '{SNAPSHOT_MONTH.isoformat()}')",
        True,
    ),
    Reload(
        "bil_fuel_schg",
        "fsc_id",
        ("carr_fsc_amt", "cust_fsc_amt"),
        f"COALESCE(i.inv_dt, DATE '{SNAPSHOT_MONTH.isoformat()}')",
        True,
    ),
    Reload(
        "bil_accsrl_chrg",
        "accsrl_id",
        ("cust_bill_amt", "carr_pay_amt"),
        "COALESCE(i.inv_dt, t.chrg_dt)",
        True,
    ),
)
TABLES = tuple(r.table for r in RELOADS)


def _guard(dataset: str) -> None:
    if dataset == RECORD:
        raise SystemExit(f"{RECORD} is the warehouse of record; plant and revert only in a copy.")


def qualified(dataset: str) -> str:
    """``project.dataset``."""
    return f"{config.project()}.{dataset}"


def plant_sql(dataset: str, since: date = RESTATED_SINCE) -> list[str]:
    """The UPDATE statements that store CAD amounts dated on or after ``since`` in US dollars.

    Each amount becomes ``ROUND(amount * rate, 2)``; ``curr_cd`` is left as ``CAD``.
    The statements touch nothing else: no row is added or removed, no column changes type.
    """
    d = qualified(dataset)
    fx = FX.format(d=d)
    statements = []
    for r in RELOADS:
        invoice = (
            f"LEFT JOIN `{d}.bil_cust_inv` AS i ON i.load_id = t.load_id" if r.needs_invoice else ""
        )
        sets = ", ".join(f"{a} = ROUND(u.{a} * s.fx_rt, 2)" for a in r.amounts)
        statements.append(
            f"UPDATE `{d}.{r.table}` AS u SET {sets}\n"
            f"FROM (SELECT t.{r.key} AS k, fx.fx_rt FROM `{d}.{r.table}` AS t {invoice}\n"
            f"      JOIN {fx} AS fx ON fx.eff_mo_dt = DATE_TRUNC({r.rate_date}, MONTH)\n"
            f"      WHERE t.curr_cd = 'CAD' AND {r.rate_date} >= DATE '{since.isoformat()}') AS s\n"
            f"WHERE u.{r.key} = s.k"
        )
    return statements


def _client() -> bigquery.Client:
    return query.client()


def _run(sql: str) -> int:
    job = _client().query(sql)
    job.result(timeout=300)
    return int(job.num_dml_affected_rows or 0)


def copy(dataset: str) -> dict[str, Any]:
    """Create ``dataset`` if needed and load every warehouse table into it from the generator."""
    _guard(dataset)
    client = _client()
    ds = bigquery.Dataset(qualified(dataset))
    ds.location = config.BQ_LOCATION
    ds.labels = {"series": "what-your-agents-dont-know", "part": "5"}
    client.create_dataset(ds, exists_ok=True)
    tables = generate.generate()
    counts = {}
    for name, rows in tables.items():
        counts[name] = load.load_table(client, name, rows, dataset=dataset)
        if counts[name] != len(rows):
            raise SystemExit(
                f"{name}: generated {len(rows)} rows but BigQuery holds {counts[name]}"
            )
    return {"dataset": dataset, "fingerprint": generate.fingerprint(tables), "rows": counts}


def plant(dataset: str, since: date = RESTATED_SINCE) -> dict[str, int]:
    """Run the reload: CAD amounts dated on or after ``since`` stored in US dollars."""
    _guard(dataset)
    return {r.table: _run(sql) for r, sql in zip(RELOADS, plant_sql(dataset, since), strict=True)}


def revert(dataset: str) -> dict[str, int]:
    """Undo the reload: load the billing tables again from the generator."""
    _guard(dataset)
    client = _client()
    tables = generate.generate()
    return {name: load.load_table(client, name, tables[name], dataset=dataset) for name in TABLES}


def status(dataset: str, record: str = RECORD) -> dict[str, Any]:
    """Compare ``dataset`` with the warehouse of record, table by table.

    Reports, for every warehouse table, the row counts and whether the column
    names and types match, and for each billing table how many rows hold an
    amount that differs from the record. A clean copy differs in 0 rows.
    """
    client = _client()
    out: dict[str, Any] = {"dataset": dataset, "record": record, "tables": {}}
    for name in schema.TABLES:
        a = client.get_table(f"{qualified(dataset)}.{name}")
        b = client.get_table(f"{qualified(record)}.{name}")
        out["tables"][name] = {
            "rows": int(a.num_rows or 0),
            "rows_in_record": int(b.num_rows or 0),
            "same_columns_and_types": [(f.name, f.field_type) for f in a.schema]
            == [(f.name, f.field_type) for f in b.schema],
        }
    for r in RELOADS:
        differs = " OR ".join(f"a.{c} != b.{c}" for c in r.amounts)
        sql = (
            f"SELECT COUNTIF({differs}) AS changed, COUNTIF(a.curr_cd = 'CAD' AND ({differs})) AS changed_cad,"
            f" COUNTIF(a.curr_cd != b.curr_cd) AS currency_code_changed"
            f" FROM `{qualified(dataset)}.{r.table}` AS a JOIN `{qualified(record)}.{r.table}` AS b USING ({r.key})"
        )
        row = next(iter(client.query(sql).result(timeout=120)))
        out["tables"][r.table].update(
            {
                "rows_with_a_changed_amount": int(row["changed"]),
                "of_which_cad": int(row["changed_cad"]),
                "rows_with_a_changed_currency_code": int(row["currency_code_changed"]),
            }
        )
    out["changed_rows"] = sum(out["tables"][t]["rows_with_a_changed_amount"] for t in TABLES)
    out["clean"] = out["changed_rows"] == 0
    return out


def gold_on(dataset: str) -> dict[str, Any]:
    """Run every reviewed gold query against ``dataset`` and compare with the frozen answers.

    Measurement only: this is what a recomputed answer key would say. It is never
    used to score a run.
    """
    gs = golden_set.load()
    client = _client()
    job_config = bigquery.QueryJobConfig(
        default_dataset=qualified(dataset), use_legacy_sql=False,
        maximum_bytes_billed=query.MAX_BYTES_BILLED,
    )  # fmt: skip
    result: dict[str, Any] = {"dataset": dataset, "golden_set_version": gs.version, "questions": {}}
    for q in gs.questions:
        try:
            rows = list(client.query(q.gold_sql, job_config=job_config).result(timeout=120))
            value = query._plain(rows[0][0])
        except gax.GoogleAPICallError as exc:
            value = f"error: {exc}"[:200]
        frozen = gs.gold(q.id)
        result["questions"][q.id] = {
            "frozen": frozen,
            "recomputed": value,
            "within_tolerance": within(q, value, frozen),
            "change_pct": _change(value, frozen),
        }
    moved = [k for k, v in result["questions"].items() if not v["within_tolerance"]]
    result["out_of_tolerance"] = moved
    result["out_of_tolerance_count"] = len(moved)
    return result


def within(q: questions.Question, value: Any, frozen: Any) -> bool:
    """Whether a recomputed value still matches the frozen one under the question's tolerance."""
    if q.answer_type == "text":
        return str(value) == str(frozen)
    try:
        return scoring.numbers_match(
            float(value), float(frozen), q.tolerance_kind, q.tolerance_value
        )
    except (TypeError, ValueError):
        return False


def _change(value: Any, frozen: Any) -> float | None:
    try:
        v, f = float(value), float(frozen)
    except (TypeError, ValueError):
        return None
    return round(100.0 * (v - f) / f, 2) if f else None


def main() -> None:
    """Command line: copy, plant, revert, status, gold."""
    parser = argparse.ArgumentParser(
        description="Part 5's planted drift, in a copy of the warehouse."
    )
    parser.add_argument("action", choices=["copy", "plant", "revert", "status", "gold", "sql"])
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--since", default=RESTATED_SINCE.isoformat())
    args = parser.parse_args()
    since = date.fromisoformat(args.since)
    if args.action == "sql":
        print(";\n\n".join(plant_sql(args.dataset, since)).replace(config.project(), "PROJECT"))
        return
    action = {
        "copy": lambda: copy(args.dataset),
        "plant": lambda: plant(args.dataset, since),
        "revert": lambda: revert(args.dataset),
        "status": lambda: status(args.dataset),
        "gold": lambda: gold_on(args.dataset),
    }[args.action]
    print(json.dumps(action(), indent=1, default=str))


if __name__ == "__main__":
    main()
