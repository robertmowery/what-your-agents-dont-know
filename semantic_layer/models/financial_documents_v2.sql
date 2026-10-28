-- Part 7: the same financial documents as `financial_documents`, dated the way
-- revenue version 2 and margin version 2 say (data/DEFINITIONS.md):
--   invoice            revenue and the load's carrier cost belong to the period
--                      the load was delivered: arrival at the final delivery
--                      stop, on the local clock at that stop
--   credit_memo        belongs to the period its load was delivered
--   canceled_load_fee  no delivery; stays in the period of the fee date
-- Amounts are exactly version 1's: Canadian-dollar documents convert at the
-- monthly rate for the month of the document date.
with delivery as (
    select load_id, date(arr_ts, tz_nm) as delivery_date
    from {{ source('warehouse', 'tms_stop') }}
    where stop_typ_cd = 'DL'
    qualify row_number() over (partition by load_id order by stop_seq desc) = 1
)

select
    d.document_id,
    d.document_type,
    d.tender_id,
    d.document_date,
    case
        when d.document_type in ('invoice', 'credit_memo') then dl.delivery_date
        else d.document_date
    end as recognition_date,
    d.document_currency,
    d.revenue_usd,
    d.carrier_cost_usd
from {{ ref('financial_documents') }} as d
left join delivery as dl on dl.load_id = d.tender_id
