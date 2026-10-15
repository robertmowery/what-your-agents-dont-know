-- One row per delivered load, per `delivered_load`: status DLVD on the row of
-- the carrier that hauled it (the final tender), never a test row and never a
-- voided row, dated at the last delivery stop on the clock at that stop.
--
-- Three flags are worked out here, row by row, because MetricFlow has no way
-- to say them:
--   arrived_on_time  `on_time` and `local_time`: arrival at the final delivery
--                    stop at or before the end of the appointment window, both
--                    on the facility's clock
--   shipper_delayed  `on_time`: a DLAY status event with reason SHPR
--   has_signed_pod   `billable`: a row in bil_pod_doc with signed_flg true
-- What the flags mean for a metric is said in semantic.yml, not here.
with final_stop as (
    select load_id, tz_nm, arr_ts, appt_end_lcl
    from {{ source('warehouse', 'tms_stop') }}
    where stop_typ_cd = 'DL'
    qualify row_number() over (partition by load_id order by stop_seq desc) = 1
),

shipper_delay as (
    select distinct load_id
    from {{ source('warehouse', 'tms_stat_evt') }}
    where evt_cd = 'DLAY' and rsn_cd = 'SHPR'
),

signed_pod as (
    select distinct load_id
    from {{ source('warehouse', 'bil_pod_doc') }}
    where signed_flg
)

select
    h.load_id as tender_id,
    parent.acct_id as customer_id,
    date(s.arr_ts, s.tz_nm) as delivered_date,
    datetime(s.arr_ts, s.tz_nm) <= s.appt_end_lcl as arrived_on_time,
    d.load_id is not null as shipper_delayed,
    p.load_id is not null as has_signed_pod
from {{ source('warehouse', 'tms_load_hdr') }} as h
inner join final_stop as s on s.load_id = h.load_id
inner join {{ source('warehouse', 'mdm_cust_acct') }} as site
    on site.acct_id = h.shpr_acct_id
inner join {{ source('warehouse', 'mdm_cust_acct') }} as parent
    on parent.acct_id = site.prnt_acct_id
left join shipper_delay as d on d.load_id = h.load_id
left join signed_pod as p on p.load_id = h.load_id
where h.load_stat_cd = 'DLVD'
    and not h.test_flg
    and not h.void_flg
