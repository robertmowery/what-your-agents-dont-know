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

"""Part 5: the planted drift touches only Canadian amounts, only in a copy, and nothing else."""

from __future__ import annotations

from datetime import date

import pytest

from tessaway import drift
from tessaway.warehouse import schema


def test_every_amount_column_on_a_billing_table_is_reloaded() -> None:
    for r in drift.RELOADS:
        cols = dict(schema.TABLES[r.table])
        assert "curr_cd" in cols
        for a in r.amounts:
            assert cols[a] == "NUMERIC", (r.table, a)
        numeric = {c for c, k in schema.TABLES[r.table] if k == "NUMERIC"}
        assert numeric == set(r.amounts), r.table


def test_no_other_table_with_a_currency_is_touched_but_the_load_header() -> None:
    with_currency = {t for t, cols in schema.TABLES.items() if any(c == "curr_cd" for c, _ in cols)}
    assert with_currency - set(drift.TABLES) == {
        "tms_load_hdr"
    }  # the TMS keeps its own rated amounts


def test_the_statements_update_cad_rows_only_and_keep_the_currency_code() -> None:
    for sql in drift.plant_sql("tessaway_wh_p5"):
        assert sql.startswith("UPDATE ")
        assert "curr_cd = 'CAD'" in sql
        assert "SET curr_cd" not in sql and "curr_cd =" not in sql.split("FROM")[0]
        assert "ROUND(" in sql and "fx_rt" in sql
        assert "DELETE" not in sql and "INSERT" not in sql
        assert ".tessaway_wh_p5." in sql and ".tessaway_wh." not in sql


def test_costs_on_an_invoiced_load_use_the_invoice_month() -> None:
    by_table = dict(zip(drift.TABLES, drift.plant_sql("tessaway_wh_p5"), strict=True))
    for table in ("bil_carr_pay", "bil_fuel_schg", "bil_accsrl_chrg"):
        assert "COALESCE(i.inv_dt" in by_table[table]
        assert "LEFT JOIN" in by_table[table]
    assert "DATE_TRUNC(t.inv_dt, MONTH)" in by_table["bil_cust_inv"]
    assert "DATE_TRUNC(t.cr_dt, MONTH)" in by_table["bil_cr_memo"]


def test_the_start_date_bounds_the_reload() -> None:
    sql = drift.plant_sql("tessaway_wh_p5", date(2026, 10, 1))[0]
    assert ">= DATE '2026-10-01'" in sql


def test_the_warehouse_of_record_is_refused() -> None:
    for action in (lambda: drift.plant("tessaway_wh"), lambda: drift.revert("tessaway_wh"),
                   lambda: drift.copy("tessaway_wh")):  # fmt: skip
        with pytest.raises(SystemExit):
            action()
