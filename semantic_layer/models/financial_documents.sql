-- One row per financial document, per `revenue`, `margin` and `currency`:
--   invoice            revenue is the invoice total; carrier cost is linehaul
--                      pay plus the carrier's fuel surcharge plus accessorials
--                      paid to the carrier, and follows the load into the
--                      period of the invoice date
--   credit_memo        negative revenue, in the period of the credit date
--   canceled_load_fee  the customer's fee is revenue and the carrier's share
--                      is cost, both in the period of the fee date
-- Every amount is put into US dollars here: Canadian-dollar documents convert
-- at the monthly rate in ref_fx_rate for the month of the document date, and
-- costs on an invoiced load convert at the invoice month's rate.
with fx as (
    select eff_mo_dt, fx_rt
    from {{ source('warehouse', 'ref_fx_rate') }}
    where from_curr_cd = 'CAD' and to_curr_cd = 'USD'
),

accessorial as (
    select load_id, sum(carr_pay_amt) as carr_accsrl_amt
    from {{ source('warehouse', 'bil_accsrl_chrg') }}
    group by load_id
),

documents as (
    select
        i.inv_id as document_id,
        'invoice' as document_type,
        i.load_id as tender_id,
        i.inv_dt as document_date,
        i.curr_cd,
        i.inv_tot_amt as revenue_amt,
        ifnull(p.lh_pay_amt, 0) + ifnull(s.carr_fsc_amt, 0) + ifnull(a.carr_accsrl_amt, 0)
            as carrier_cost_amt
    from {{ source('warehouse', 'bil_cust_inv') }} as i
    left join {{ source('warehouse', 'bil_carr_pay') }} as p on p.load_id = i.load_id
    left join {{ source('warehouse', 'bil_fuel_schg') }} as s on s.load_id = i.load_id
    left join accessorial as a on a.load_id = i.load_id

    union all

    select
        c.cr_memo_id, 'credit_memo', c.load_id, c.cr_dt, c.curr_cd, -c.cr_amt, 0
    from {{ source('warehouse', 'bil_cr_memo') }} as c

    union all

    select
        f.canc_fee_id, 'canceled_load_fee', f.load_id, f.fee_dt, f.curr_cd,
        f.cust_fee_amt, f.carr_fee_amt
    from {{ source('warehouse', 'bil_canc_fee') }} as f
)

select
    d.document_id,
    d.document_type,
    d.tender_id,
    d.document_date,
    d.curr_cd as document_currency,
    d.revenue_amt * if(d.curr_cd = 'CAD', fx.fx_rt, 1) as revenue_usd,
    d.carrier_cost_amt * if(d.curr_cd = 'CAD', fx.fx_rt, 1) as carrier_cost_usd
from documents as d
left join fx on fx.eff_mo_dt = date_trunc(d.document_date, month)
