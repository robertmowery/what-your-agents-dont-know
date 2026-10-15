-- One row per row of tms_load_hdr. Per the `load` definition a row there is a
-- tender, not a load. This view only attaches names: the shipping site, the
-- customer (the parent account the site rolls up to, per `customer`), the
-- bill-to party and the carrier. Nothing is filtered out.
select
    h.load_id as tender_id,
    h.load_stat_cd as tender_status,
    h.xbrdr_flg as is_cross_border,
    h.curr_cd as rated_currency,
    h.eqp_typ_cd as equipment_type,
    h.test_flg as is_test,
    h.void_flg as is_void,
    h.orig_load_id is not null as is_retender,
    site.acct_id as shipper_site_id,
    site.acct_nm as shipper_site_name,
    parent.acct_id as customer_id,
    parent.acct_nm as customer_name,
    bill_to.acct_id as bill_to_party_id,
    bill_to.acct_nm as bill_to_party_name,
    carrier.carr_id as carrier_id,
    carrier.carr_nm as carrier_name,
    carrier.carr_typ_cd as carrier_type
from {{ source('warehouse', 'tms_load_hdr') }} as h
inner join {{ source('warehouse', 'mdm_cust_acct') }} as site
    on site.acct_id = h.shpr_acct_id
inner join {{ source('warehouse', 'mdm_cust_acct') }} as parent
    on parent.acct_id = site.prnt_acct_id
inner join {{ source('warehouse', 'mdm_cust_acct') }} as bill_to
    on bill_to.acct_id = h.bill_to_acct_id
inner join {{ source('warehouse', 'tms_carr') }} as carrier
    on carrier.carr_id = h.carr_id
