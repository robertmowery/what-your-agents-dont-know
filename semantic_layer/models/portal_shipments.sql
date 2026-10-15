-- One row per shipment the customer portal shows as delivered, per
-- `portal_on_time`: the portal's own flag, which compares the delivery date
-- with the date the customer requested and knows nothing about appointment
-- times or who caused a delay.
select
    shpmt_ref as shipment_ref,
    load_id as tender_id,
    actl_dlvr_dt as portal_delivered_date,
    on_time_ind = 'Y' as portal_on_time
from {{ source('warehouse', 'ptl_shpmt') }}
where actl_dlvr_dt is not null
