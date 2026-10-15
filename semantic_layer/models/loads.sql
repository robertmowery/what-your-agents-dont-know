-- One row per load, per the `load` definition: a shipment counted once, from
-- its first tender (the row where orig_load_id is empty), never a test row
-- and never a voided row. The load is booked on the UTC date of that first
-- tender (`local_time`: booking dates use the UTC date of crt_ts).
select
    h.load_id as load_id,
    h.load_id as first_tender_id,
    date(h.crt_ts) as booked_date
from {{ source('warehouse', 'tms_load_hdr') }} as h
where h.orig_load_id is null
    and not h.test_flg
    and not h.void_flg
