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

"""The Tessaway Freight warehouse schema: table names, column names and types.

Tessaway Freight is a fictional company. The schema models three source
systems landed in one warehouse, the way a real one looks after a few years:

    tms_*   transportation management: loads, stops, status events
    bil_*   carrier billing: invoices, carrier pay, surcharges, credits
    ptl_*   customer portal: the shipment view customers see
    mdm_*   customer master data
    ref_*   reference data

This module is the single source for the schema. The load script builds the
BigQuery tables from it, and the agents are shown exactly what
``render_for_agent`` returns: names and types, nothing about meaning.
"""

from __future__ import annotations

# Table name -> ordered (column name, BigQuery type) pairs.
TABLES: dict[str, list[tuple[str, str]]] = {
    "tms_load_hdr": [
        ("load_id", "STRING"),
        ("orig_load_id", "STRING"),
        ("shpr_acct_id", "STRING"),
        ("bill_to_acct_id", "STRING"),
        ("carr_id", "STRING"),
        ("load_stat_cd", "STRING"),
        ("eqp_typ_cd", "STRING"),
        ("orig_fac_id", "STRING"),
        ("dest_fac_id", "STRING"),
        ("miles_qty", "INT64"),
        ("xbrdr_flg", "BOOL"),
        ("curr_cd", "STRING"),
        ("lh_rev_amt", "NUMERIC"),
        ("lh_cost_amt", "NUMERIC"),
        ("req_dlvr_dt", "DATE"),
        ("test_flg", "BOOL"),
        ("void_flg", "BOOL"),
        ("crt_ts", "TIMESTAMP"),
        ("upd_ts", "TIMESTAMP"),
    ],
    "tms_stop": [
        ("stop_id", "STRING"),
        ("load_id", "STRING"),
        ("stop_seq", "INT64"),
        ("stop_typ_cd", "STRING"),
        ("fac_id", "STRING"),
        ("tz_nm", "STRING"),
        ("appt_start_lcl", "DATETIME"),
        ("appt_end_lcl", "DATETIME"),
        ("arr_ts", "TIMESTAMP"),
        ("dep_ts", "TIMESTAMP"),
    ],
    "tms_stat_evt": [
        ("evt_id", "STRING"),
        ("load_id", "STRING"),
        ("stop_id", "STRING"),
        ("evt_cd", "STRING"),
        ("rsn_cd", "STRING"),
        ("evt_ts", "TIMESTAMP"),
        ("src_cd", "STRING"),
    ],
    "tms_fac": [
        ("fac_id", "STRING"),
        ("fac_nm", "STRING"),
        ("city_nm", "STRING"),
        ("st_prov_cd", "STRING"),
        ("ctry_cd", "STRING"),
        ("tz_nm", "STRING"),
    ],
    "tms_carr": [
        ("carr_id", "STRING"),
        ("carr_nm", "STRING"),
        ("scac_cd", "STRING"),
        ("carr_typ_cd", "STRING"),
        ("actv_flg", "BOOL"),
    ],
    "mdm_cust_acct": [
        ("acct_id", "STRING"),
        ("acct_nm", "STRING"),
        ("acct_typ_cd", "STRING"),
        ("prnt_acct_id", "STRING"),
        ("seg_cd", "STRING"),
        ("ctry_cd", "STRING"),
        ("actv_flg", "BOOL"),
    ],
    "bil_cust_inv": [
        ("inv_id", "STRING"),
        ("load_id", "STRING"),
        ("bill_to_acct_id", "STRING"),
        ("inv_dt", "DATE"),
        ("curr_cd", "STRING"),
        ("inv_tot_amt", "NUMERIC"),
        ("inv_stat_cd", "STRING"),
    ],
    "bil_pod_doc": [
        ("pod_doc_id", "STRING"),
        ("load_id", "STRING"),
        ("rcvd_ts", "TIMESTAMP"),
        ("signed_flg", "BOOL"),
        ("doc_src_cd", "STRING"),
    ],
    "bil_carr_pay": [
        ("pay_id", "STRING"),
        ("load_id", "STRING"),
        ("carr_id", "STRING"),
        ("lh_pay_amt", "NUMERIC"),
        ("curr_cd", "STRING"),
        ("pay_stat_cd", "STRING"),
        ("pay_dt", "DATE"),
    ],
    "bil_fuel_schg": [
        ("fsc_id", "STRING"),
        ("load_id", "STRING"),
        ("cust_fsc_amt", "NUMERIC"),
        ("carr_fsc_amt", "NUMERIC"),
        ("curr_cd", "STRING"),
    ],
    "bil_accsrl_chrg": [
        ("accsrl_id", "STRING"),
        ("load_id", "STRING"),
        ("accsrl_cd", "STRING"),
        ("cust_bill_amt", "NUMERIC"),
        ("carr_pay_amt", "NUMERIC"),
        ("curr_cd", "STRING"),
        ("chrg_dt", "DATE"),
    ],
    "bil_cr_memo": [
        ("cr_memo_id", "STRING"),
        ("load_id", "STRING"),
        ("inv_id", "STRING"),
        ("bill_to_acct_id", "STRING"),
        ("cr_amt", "NUMERIC"),
        ("cr_rsn_cd", "STRING"),
        ("cr_dt", "DATE"),
        ("curr_cd", "STRING"),
    ],
    "bil_canc_fee": [
        ("canc_fee_id", "STRING"),
        ("load_id", "STRING"),
        ("cust_fee_amt", "NUMERIC"),
        ("carr_fee_amt", "NUMERIC"),
        ("curr_cd", "STRING"),
        ("fee_dt", "DATE"),
    ],
    "ref_fx_rate": [
        ("eff_mo_dt", "DATE"),
        ("from_curr_cd", "STRING"),
        ("to_curr_cd", "STRING"),
        ("fx_rt", "NUMERIC"),
    ],
    "ptl_shpmt": [
        ("shpmt_ref", "STRING"),
        ("load_id", "STRING"),
        ("cust_acct_id", "STRING"),
        ("stat_txt", "STRING"),
        ("req_dlvr_dt", "DATE"),
        ("actl_dlvr_dt", "DATE"),
        ("on_time_ind", "STRING"),
        ("last_upd_ts", "TIMESTAMP"),
    ],
}

# Columns that are allowed to be empty. Every other column is filled on every
# row; the generator tests enforce this, because the experiment depends on the
# data being complete.
NULLABLE: dict[str, set[str]] = {
    "tms_load_hdr": {"orig_load_id"},
    "tms_stop": {"arr_ts", "dep_ts"},
    "tms_stat_evt": {"stop_id", "rsn_cd"},
    "mdm_cust_acct": {"prnt_acct_id"},
    "bil_carr_pay": {"pay_dt"},
    "ptl_shpmt": {"actl_dlvr_dt", "on_time_ind"},
}


def render_for_agent() -> str:
    """Return the schema as the agents see it: table, column and type names only."""
    blocks = []
    for table, columns in TABLES.items():
        lines = [f"{table}"] + [f"  {name} {kind}" for name, kind in columns]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
