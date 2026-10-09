# Tessaway Freight: official definitions

Tessaway Freight is a fictional company. These are the definitions its people would give you if you asked: the operations lead, the controller, the account managers. They decide which answer to each question in `questions/part1.yaml` is correct.

**The agents never see this file.** In Part 1 the agents get table names, column names and types, and one tool that runs read-only SQL. Nothing in the warehouse states any of what follows. That is the experiment.

This file was written before any agent ran. It is not edited to fit results.

## `load`

A load is one shipment moved for a customer, counted once.

- A row in `tms_load_hdr` is a tender, not a load. When the first carrier accepts a load and then falls off, the load is tendered again and a second row is written. The second row points to the first through `orig_load_id`. The first row keeps status `RTND` and is never deleted. Both rows carry the same linehaul revenue.
- Test loads (`test_flg`) are entered by the systems team to check integrations. They move through every status, including delivered. They are not loads.
- Voided loads (`void_flg`) were entered in error. They are not loads.
- A load is booked on the date of its first tender: the row where `orig_load_id` is empty.
- A canceled load was a load, and counts as booked. It does not count as delivered.

## `delivered_load`

For operations, a load is delivered when the carrier reports the final delivery: status `DLVD`. Delivered counts and service measures use this meaning.

- Only real loads count: not test rows, not voided rows. A re-tendered load is delivered once, by the carrier on its final row.
- A delivered load belongs to the calendar day, month and quarter of its arrival at the final delivery stop, on the clock at that stop (see `local_time`).
- A load with two delivery stops is delivered once, at the last one.

## `billable`

For billing, delivered is not enough. A load can be invoiced only when a signed proof of delivery is on file: a row in `bil_pod_doc` with `signed_flg` true. An unsigned document does not count.

- The invoice is cut the day the signed proof of delivery is received. A delivered load without one has no invoice and no revenue yet.
- Test loads are never billed. They are not waiting on anything.

## `on_time`

Tessaway's official on-time delivery rate is the one its customer contracts define.

- A load is on time when the truck arrives at the final delivery stop at or before the end of the appointment window. Arriving early is on time.
- Arrival and appointment are compared on the same clock: local time at the facility (see `local_time`).
- A load that arrived late and has a delay the shipper caused (a `DLAY` status event with reason `SHPR`) is left out of the measure, top and bottom. It is neither on time nor late.
- A load the shipper delayed that still arrived inside its window counts as on time.
- The rate is on-time loads divided by measured loads, over delivered loads (see `delivered_load`).

Two other meanings are in use and are not the official rate:

- Operations watches arrival inside the appointment window for every delivered load, shipper-caused or not.
- The customer portal uses its own rule (see `portal_on_time`).

## `portal_on_time`

The customer portal shows a shipment as on time when it was delivered on or before the date the customer requested (`ptl_shpmt.on_time_ind`). It compares dates, not appointment times, and knows nothing about who caused a delay. It is the right answer only when the question is about what customers see in the portal.

## `customer`

A customer is a parent account: a row in `mdm_cust_acct` with `acct_typ_cd = 'PRNT'`.

- The account on a load (`shpr_acct_id`) is a shipping site. Several sites roll up to one parent through `prnt_acct_id`, and a site does not always carry the parent's name. Northgate Foods Group ships under Northgate Foods, Harlow Dairy Co. and Sunmeadow Bakeries.
- The account on an invoice (`bill_to_acct_id`) is whoever pays. It may be a shared accounts payable office or a freight payment firm that pays on behalf of several customers. A bill-to party is not the customer.
- Revenue and loads belong to the parent of the site that shipped.
- A customer shipped with us in a period if at least one of its loads was delivered in that period.

## `revenue`

Revenue is recognized when it is invoiced, in the period of the invoice date.

- It is the invoice total (`bil_cust_inv.inv_tot_amt`), which already includes linehaul, fuel surcharge and accessorial charges billed to the customer,
- less credit memos (`bil_cr_memo`), in the period of the credit date,
- plus canceled-load fees billed to the customer (`bil_canc_fee.cust_fee_amt`), in the period of the fee date,
- all in US dollars (see `currency`).

`tms_load_hdr.lh_rev_amt` is the rated linehaul on a tender. It is not revenue: it leaves out fuel and accessorials, and it sits on canceled, test, voided and re-tendered rows that were never billed.

## `margin`

Margin is revenue less what was paid to carriers for the same loads.

- Carrier cost for an invoiced load is linehaul pay (`bil_carr_pay.lh_pay_amt`) plus the carrier's fuel surcharge (`bil_fuel_schg.carr_fsc_amt`) plus accessorials paid to the carrier (`bil_accsrl_chrg.carr_pay_amt`). Cost follows the load into the period its invoice was cut.
- The carrier's share of a canceled-load fee (`bil_canc_fee.carr_fee_amt`) is a cost in the period of the fee date.
- Margin per load is margin for the period divided by the number of loads invoiced in the period.
- Margin percentage is margin divided by revenue.
- Loads hauled by Tessaway's own fleet are settled through the same tables and are treated the same way.

## `currency`

Tessaway reports in US dollars.

- Most cross-border loads are rated, invoiced and paid in Canadian dollars. Every amount on such a load carries `curr_cd = 'CAD'` and is stored unconverted.
- Convert at the monthly rate in `ref_fx_rate` for the month of the document date: the invoice date, the credit date or the fee date. Costs on an invoiced load convert at the invoice month's rate.

## `local_time`

- Every `*_ts` column is an instant stored in UTC.
- Every `*_lcl` column is a wall-clock time at the facility, with no zone attached. The zone is in `tz_nm` on the stop and on the facility.
- Operational dates are local: a delivery happened on the calendar day it was at the destination. A truck that arrives in Dallas at 8:00 p.m. on the 11th arrived on the 11th, although the stored instant is 1:00 a.m. on the 12th.
- Appointment times are compared with arrival times only after putting both on the same clock.
- Booking dates use the UTC date of `crt_ts`. Financial dates (`inv_dt`, `cr_dt`, `fee_dt`) are plain dates and need no conversion.
