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

"""Claims the Part 1 articles make about the data, checked without any cloud call.

The warehouse must be complete and its joins valid, and every trap in
data/TRAPS.md must really be in the rows.
"""

from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from tessaway.warehouse import generate, schema

# The fingerprint of the warehouse the saved results were measured on. If the
# generator changes, this fails and the results no longer describe the data.
FINGERPRINT = "2b8171584cfe787225e454be0651d59404d6809e70c4b11bb8181ed48058e5d8"

SEPTEMBER = (date(2026, 9, 1), date(2026, 9, 30))


@pytest.fixture(scope="module")
def wh() -> generate.Tables:
    return generate.generate()


def ts(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def final_delivery_stops(wh: generate.Tables) -> dict[str, generate.Row]:
    last: dict[str, generate.Row] = {}
    for stop in wh["tms_stop"]:
        if stop["stop_typ_cd"] == "DL" and (
            stop["load_id"] not in last or stop["stop_seq"] > last[stop["load_id"]]["stop_seq"]
        ):
            last[stop["load_id"]] = stop
    return last


def delivered(wh: generate.Tables) -> list[generate.Row]:
    """Real delivered loads, on the official definition."""
    return [
        row
        for row in wh["tms_load_hdr"]
        if row["load_stat_cd"] == "DLVD" and not row["test_flg"] and not row["void_flg"]
    ]


# --- the data is not broken ----------------------------------------------------


def test_same_seed_gives_the_same_warehouse() -> None:
    assert generate.fingerprint(generate.generate()) == generate.fingerprint(generate.generate())


def test_warehouse_matches_the_one_the_results_were_measured_on(wh: generate.Tables) -> None:
    assert generate.fingerprint(wh) == FINGERPRINT


def test_a_different_seed_gives_different_data() -> None:
    assert generate.fingerprint(generate.generate(seed=1)) != FINGERPRINT


def test_every_row_has_exactly_the_schema_columns(wh: generate.Tables) -> None:
    assert set(wh) == set(schema.TABLES)
    for table, rows in wh.items():
        columns = [name for name, _ in schema.TABLES[table]]
        assert rows, f"{table} is empty"
        assert all(list(row) == columns for row in rows), table


def test_tables_are_complete(wh: generate.Tables) -> None:
    for table, rows in wh.items():
        nullable = schema.NULLABLE.get(table, set())
        for row in rows:
            empty = {col for col, value in row.items() if value is None} - nullable
            assert not empty, f"{table} has an empty {empty}"


def test_primary_keys_are_unique(wh: generate.Tables) -> None:
    keys = {
        "tms_load_hdr": "load_id", "tms_stop": "stop_id", "tms_stat_evt": "evt_id",
        "tms_fac": "fac_id", "tms_carr": "carr_id", "mdm_cust_acct": "acct_id",
        "bil_cust_inv": "inv_id", "bil_pod_doc": "pod_doc_id", "bil_carr_pay": "pay_id",
        "bil_fuel_schg": "fsc_id", "bil_accsrl_chrg": "accsrl_id", "bil_cr_memo": "cr_memo_id",
        "bil_canc_fee": "canc_fee_id", "ptl_shpmt": "shpmt_ref",
    }  # fmt: skip
    for table, key in keys.items():
        values = [row[key] for row in wh[table]]
        assert len(values) == len(set(values)), table


def test_every_join_key_resolves(wh: generate.Tables) -> None:
    ids = {
        "load": {r["load_id"] for r in wh["tms_load_hdr"]},
        "stop": {r["stop_id"] for r in wh["tms_stop"]},
        "fac": {r["fac_id"] for r in wh["tms_fac"]},
        "carr": {r["carr_id"] for r in wh["tms_carr"]},
        "acct": {r["acct_id"] for r in wh["mdm_cust_acct"]},
        "inv": {r["inv_id"] for r in wh["bil_cust_inv"]},
    }
    joins = [
        ("tms_load_hdr", "orig_load_id", "load"), ("tms_load_hdr", "shpr_acct_id", "acct"),
        ("tms_load_hdr", "bill_to_acct_id", "acct"), ("tms_load_hdr", "carr_id", "carr"),
        ("tms_load_hdr", "orig_fac_id", "fac"), ("tms_load_hdr", "dest_fac_id", "fac"),
        ("tms_stop", "load_id", "load"), ("tms_stop", "fac_id", "fac"),
        ("tms_stat_evt", "load_id", "load"), ("tms_stat_evt", "stop_id", "stop"),
        ("mdm_cust_acct", "prnt_acct_id", "acct"),
        ("bil_cust_inv", "load_id", "load"), ("bil_cust_inv", "bill_to_acct_id", "acct"),
        ("bil_pod_doc", "load_id", "load"), ("bil_carr_pay", "load_id", "load"),
        ("bil_carr_pay", "carr_id", "carr"), ("bil_fuel_schg", "load_id", "load"),
        ("bil_accsrl_chrg", "load_id", "load"), ("bil_cr_memo", "load_id", "load"),
        ("bil_cr_memo", "inv_id", "inv"), ("bil_cr_memo", "bill_to_acct_id", "acct"),
        ("bil_canc_fee", "load_id", "load"), ("ptl_shpmt", "load_id", "load"),
        ("ptl_shpmt", "cust_acct_id", "acct"),
    ]  # fmt: skip
    for table, column, target in joins:
        dangling = {r[column] for r in wh[table] if r[column] is not None} - ids[target]
        assert not dangling, f"{table}.{column} has keys with no match"


def test_every_load_has_a_pickup_and_a_delivery_stop(wh: generate.Tables) -> None:
    kinds: dict[str, set[str]] = defaultdict(set)
    for stop in wh["tms_stop"]:
        kinds[stop["load_id"]].add(stop["stop_typ_cd"])
    assert all(kinds[r["load_id"]] == {"PU", "DL"} for r in wh["tms_load_hdr"])


def test_nothing_happens_after_the_snapshot(wh: generate.Tables) -> None:
    assert max(ts(e["evt_ts"]) for e in wh["tms_stat_evt"]) <= generate.SNAPSHOT
    assert max(ts(p["rcvd_ts"]) for p in wh["bil_pod_doc"]) <= generate.SNAPSHOT
    assert max(i["inv_dt"] for i in wh["bil_cust_inv"]) <= generate.SNAPSHOT.date().isoformat()


def test_a_fx_rate_exists_for_every_month_money_was_booked(wh: generate.Tables) -> None:
    months = {r["eff_mo_dt"][:7] for r in wh["ref_fx_rate"] if r["from_curr_cd"] == "CAD"}
    dated = [("bil_cust_inv", "inv_dt"), ("bil_cr_memo", "cr_dt"), ("bil_canc_fee", "fee_dt")]
    for table, column in dated:
        assert {r[column][:7] for r in wh[table]} <= months


# --- trap: on-time has three meanings ------------------------------------------


def on_time_rates(wh: generate.Tables) -> dict[str, float]:
    """September on-time under each meaning, computed the long way in Python."""
    last = final_delivery_stops(wh)
    shipper_delay = {
        e["load_id"] for e in wh["tms_stat_evt"] if e["evt_cd"] == "DLAY" and e["rsn_cd"] == "SHPR"
    }
    on_time = late = late_shipper = naive_on_time = 0
    for load in delivered(wh):
        stop = last[load["load_id"]]
        arrived_local = ts(stop["arr_ts"]).astimezone(ZoneInfo(stop["tz_nm"])).replace(tzinfo=None)
        if not SEPTEMBER[0] <= arrived_local.date() <= SEPTEMBER[1]:
            continue
        window_end = datetime.fromisoformat(stop["appt_end_lcl"])
        naive_on_time += ts(stop["arr_ts"]).replace(tzinfo=None) <= window_end
        if arrived_local <= window_end:
            on_time += 1
        elif load["load_id"] in shipper_delay:
            late_shipper += 1
        else:
            late += 1
    first, last_day = SEPTEMBER[0].isoformat(), SEPTEMBER[1].isoformat()
    portal = [
        r for r in wh["ptl_shpmt"] if r["actl_dlvr_dt"] and first <= r["actl_dlvr_dt"] <= last_day
    ]
    total = on_time + late + late_shipper
    return {
        "contract": 100 * on_time / (on_time + late),
        "operations": 100 * on_time / total,
        "portal": 100 * sum(r["on_time_ind"] == "Y" for r in portal) / len(portal),
        "utc_mistake": 100 * naive_on_time / total,
    }


def test_three_meanings_of_on_time_give_three_different_rates(wh: generate.Tables) -> None:
    rates = on_time_rates(wh)
    assert rates["operations"] + 2 < rates["contract"] < rates["portal"] - 2


def test_comparing_utc_to_local_appointments_wrecks_the_rate(wh: generate.Tables) -> None:
    rates = on_time_rates(wh)
    assert rates["utc_mistake"] < 10 < rates["operations"]


def test_official_on_time_rate_matches_the_gold_answer(wh: generate.Tables) -> None:
    # 87.44 is the answer the gold SQL returns from BigQuery for question M1.
    assert round(on_time_rates(wh)["contract"], 2) == 87.44


# --- trap: delivered is not billable -------------------------------------------


def test_some_delivered_loads_have_no_signed_proof_of_delivery(wh: generate.Tables) -> None:
    signed = {p["load_id"] for p in wh["bil_pod_doc"] if p["signed_flg"]}
    unsigned_only = {p["load_id"] for p in wh["bil_pod_doc"]} - signed
    real = {r["load_id"] for r in delivered(wh)}
    assert len(real - signed) > 100
    assert unsigned_only, "some loads hold only an unsigned document"


def test_an_invoice_exists_exactly_when_a_signed_proof_of_delivery_does(
    wh: generate.Tables,
) -> None:
    signed = {p["load_id"] for p in wh["bil_pod_doc"] if p["signed_flg"]}
    assert {i["load_id"] for i in wh["bil_cust_inv"]} == signed


# --- trap: margin is spread over five tables -------------------------------------


def test_invoice_total_is_linehaul_plus_fuel_plus_accessorials(wh: generate.Tables) -> None:
    linehaul = {r["load_id"]: float(r["lh_rev_amt"]) for r in wh["tms_load_hdr"]}
    fuel = {r["load_id"]: float(r["cust_fsc_amt"]) for r in wh["bil_fuel_schg"]}
    extras: dict[str, float] = defaultdict(float)
    for row in wh["bil_accsrl_chrg"]:
        extras[row["load_id"]] += float(row["cust_bill_amt"])
    for invoice in wh["bil_cust_inv"]:
        load = invoice["load_id"]
        assert float(invoice["inv_tot_amt"]) == pytest.approx(
            linehaul[load] + fuel[load] + extras[load], abs=0.011
        )


def test_credits_and_canceled_load_fees_exist_in_their_own_tables(wh: generate.Tables) -> None:
    assert len(wh["bil_cr_memo"]) > 100
    assert len(wh["bil_canc_fee"]) > 30
    canceled = {r["load_id"] for r in wh["tms_load_hdr"] if r["load_stat_cd"] == "CANC"}
    assert {r["load_id"] for r in wh["bil_canc_fee"]} <= canceled


def test_canceled_and_test_rows_still_carry_linehaul_amounts(wh: generate.Tables) -> None:
    never_billed = [
        r for r in wh["tms_load_hdr"] if r["load_stat_cd"] in {"CANC", "RTND"} or r["test_flg"]
    ]
    assert all(float(r["lh_rev_amt"]) > 0 for r in never_billed)
    billed = {i["load_id"] for i in wh["bil_cust_inv"]}
    assert not billed & {r["load_id"] for r in never_billed}


# --- trap: a customer is three rows ----------------------------------------------


def test_a_customer_is_a_parent_with_shipper_and_bill_to_rows_beneath_it(
    wh: generate.Tables,
) -> None:
    kinds = Counter(r["acct_typ_cd"] for r in wh["mdm_cust_acct"])
    assert set(kinds) == {"PRNT", "SHPR", "BLTO"}
    by_id = {r["acct_id"]: r for r in wh["mdm_cust_acct"]}
    assert all(r["prnt_acct_id"] is None for r in by_id.values() if r["acct_typ_cd"] == "PRNT")
    assert all(
        by_id[r["prnt_acct_id"]]["acct_typ_cd"] == "PRNT"
        for r in by_id.values()
        if r["acct_typ_cd"] != "PRNT"
    )
    assert {r["acct_typ_cd"] for r in wh["mdm_cust_acct"] if r["acct_id"] in
            {h["shpr_acct_id"] for h in wh["tms_load_hdr"]}} == {"SHPR"}  # fmt: skip
    assert {r["acct_typ_cd"] for r in wh["mdm_cust_acct"] if r["acct_id"] in
            {h["bill_to_acct_id"] for h in wh["tms_load_hdr"]}} == {"BLTO"}  # fmt: skip


def test_northgate_ships_under_names_that_do_not_say_northgate(wh: generate.Tables) -> None:
    by_name = {r["acct_nm"]: r for r in wh["mdm_cust_acct"]}
    parent = by_name["Northgate Foods Group"]["acct_id"]
    sites = [
        r["acct_nm"] for r in wh["mdm_cust_acct"]
        if r["prnt_acct_id"] == parent and r["acct_typ_cd"] == "SHPR"
    ]  # fmt: skip
    assert len(sites) == 6
    assert sum("Northgate" not in name for name in sites) == 2


def test_some_freight_is_billed_to_a_party_outside_the_customer(wh: generate.Tables) -> None:
    by_id = {r["acct_id"]: r for r in wh["mdm_cust_acct"]}
    outside = [
        h for h in wh["tms_load_hdr"]
        if by_id[h["shpr_acct_id"]]["prnt_acct_id"] != by_id[h["bill_to_acct_id"]]["prnt_acct_id"]
    ]  # fmt: skip
    assert len(outside) > 1000


# --- trap: a load is not a row ----------------------------------------------------


def test_re_tendered_loads_appear_twice(wh: generate.Tables) -> None:
    by_id = {r["load_id"]: r for r in wh["tms_load_hdr"]}
    second = [r for r in wh["tms_load_hdr"] if r["orig_load_id"]]
    assert len(second) > 400
    for row in second:
        first = by_id[row["orig_load_id"]]
        assert first["load_stat_cd"] == "RTND"
        assert first["lh_rev_amt"] == row["lh_rev_amt"]
        assert first["shpr_acct_id"] == row["shpr_acct_id"]
    assert sum(r["load_stat_cd"] == "RTND" for r in wh["tms_load_hdr"]) == len(second)


def test_test_and_voided_loads_are_flagged_not_deleted(wh: generate.Tables) -> None:
    test_rows = [r for r in wh["tms_load_hdr"] if r["test_flg"]]
    void_rows = [r for r in wh["tms_load_hdr"] if r["void_flg"]]
    assert len(test_rows) > 100 and len(void_rows) > 150
    assert any(r["load_stat_cd"] == "DLVD" for r in test_rows), "test loads reach delivered"
    hidden = {r["load_id"] for r in test_rows + void_rows}
    for table in ("bil_cust_inv", "bil_carr_pay", "bil_pod_doc", "ptl_shpmt"):
        assert not hidden & {r["load_id"] for r in wh[table]}, table


# --- trap: money and time ---------------------------------------------------------


def test_only_cross_border_loads_carry_canadian_dollars(wh: generate.Tables) -> None:
    cad = [r for r in wh["tms_load_hdr"] if r["curr_cd"] == "CAD"]
    assert len(cad) > 300
    assert all(r["xbrdr_flg"] for r in cad)
    assert any(r["xbrdr_flg"] and r["curr_cd"] == "USD" for r in wh["tms_load_hdr"])
    currency = {r["load_id"]: r["curr_cd"] for r in wh["tms_load_hdr"]}
    for table in ("bil_cust_inv", "bil_carr_pay", "bil_fuel_schg", "bil_accsrl_chrg",
                  "bil_cr_memo", "bil_canc_fee"):  # fmt: skip
        assert all(r["curr_cd"] == currency[r["load_id"]] for r in wh[table]), table


def test_timestamps_are_utc_and_appointments_are_local(wh: generate.Tables) -> None:
    stop = next(s for s in wh["tms_stop"] if s["arr_ts"])
    assert stop["arr_ts"].endswith("Z")
    assert "Z" not in stop["appt_end_lcl"] and "+" not in stop["appt_end_lcl"]
    assert all(ZoneInfo(s["tz_nm"]) for s in wh["tms_stop"][:200])


def test_many_deliveries_fall_on_a_different_day_in_utc(wh: generate.Tables) -> None:
    last = final_delivery_stops(wh)
    shifted = 0
    for load in delivered(wh):
        stop = last[load["load_id"]]
        arrived = ts(stop["arr_ts"])
        shifted += arrived.date() != arrived.astimezone(ZoneInfo(stop["tz_nm"])).date()
    assert shifted > 300


# --- the rows the lookup questions name --------------------------------------------


def test_the_load_named_in_a_lookup_question_is_an_ordinary_load(wh: generate.Tables) -> None:
    row = next(r for r in wh["tms_load_hdr"] if r["load_id"] == "L1004200")
    assert row["load_stat_cd"] == "DLVD" and not row["test_flg"] and not row["void_flg"]
    assert row["orig_load_id"] is None and row["miles_qty"] == 638


def test_names_used_in_lookup_questions_are_unique(wh: generate.Tables) -> None:
    assert sum(r["fac_nm"] == "Kettle Ridge Cold Storage" for r in wh["tms_fac"]) == 1
    assert sum(r["carr_nm"] == "Brightline Haulage" for r in wh["tms_carr"]) == 1
    assert len({r["scac_cd"] for r in wh["tms_carr"]}) == len(wh["tms_carr"])
