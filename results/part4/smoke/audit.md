# Part 4 audit: one wrong answer, followed home

**This run is from Part 3, not Part 4.** No Part 4 run was confidently wrong, so by the rule in `predictions.md` the audit is Part 3's routed_holdout H10 run 0. Contract 1.0.0 did not stamp definitions and Part 3's agent was not asked to cite, so the definitions served are rebuilt from the calls Part 3 recorded, through the Part 4 registry at version 1 (no definition has changed since), and each call is confirmed in Part 3's server log by its response ID.

Question H10, run 0, configuration routed_holdout. Run ID `64ba29ee-0dc9-4e75-a4cb-16c660459bd7`.

## The answer (0.0 ms)

```json
{
 "question_id": "H10",
 "trial": 0,
 "outcome": "confidently_wrong",
 "answer": "0",
 "gold": 139,
 "run_id": "64ba29ee-0dc9-4e75-a4cb-16c660459bd7",
 "final_lines": "\nTherefore, under the official definition of `late_deliveries`, exactly **0** late deliveries were the shipper's fault (while operationally, 139 delivered loads arrived after their appointment window with a shipper-caused delay).\n\nANSWER: 0"
}
```

## What the answer cites (0.01 ms)

```json
{
 "sources_line": null,
 "cited": []
}
```

## The server's record of the run (0.17 ms)

```json
{
 "contract_calls": [
  {
   "seq": 1,
   "operation": "lookup_definition",
   "arguments": {
    "term": "late"
   },
   "contract_version": "1.0.0",
   "definitions_in_response": [],
   "definitions_by_registry_mapping": [
    "on_time@1"
   ],
   "in_server_log": true,
   "server_log_definitions": null,
   "server_log_time": null,
   "result_rows": null
  },
  {
   "seq": 2,
   "operation": "lookup_definition",
   "arguments": {
    "term": "shipper delay"
   },
   "contract_version": "1.0.0",
   "definitions_in_response": [],
   "definitions_by_registry_mapping": [
    "on_time@1"
   ],
   "in_server_log": true,
   "server_log_definitions": null,
   "server_log_time": null,
   "result_rows": null
  },
  {
   "seq": 3,
   "operation": "compute_metric",
   "arguments": {
    "group_by": [
     "delivery__arrived_on_time",
     "delivery__shipper_delayed"
    ],
    "metrics": [
     "delivered_loads"
    ],
    "start_date": "2026-07-01",
    "end_date": "2026-09-30"
   },
   "contract_version": "1.0.0",
   "definitions_in_response": [],
   "definitions_by_registry_mapping": [
    "delivered_load@1"
   ],
   "in_server_log": true,
   "server_log_definitions": null,
   "server_log_time": null,
   "result_rows": [
    [
     true,
     false,
     2744
    ],
    [
     false,
     true,
     139
    ],
    [
     false,
     false,
     409
    ],
    [
     true,
     true,
     142
    ]
   ]
  },
  {
   "seq": 4,
   "operation": "compute_metric",
   "arguments": {
    "group_by": [
     "delivery__shipper_delayed"
    ],
    "metrics": [
     "late_deliveries"
    ],
    "end_date": "2026-09-30",
    "start_date": "2026-07-01"
   },
   "contract_version": "1.0.0",
   "definitions_in_response": [],
   "definitions_by_registry_mapping": [
    "on_time@1"
   ],
   "in_server_log": true,
   "server_log_definitions": null,
   "server_log_time": null,
   "result_rows": [
    [
     false,
     409
    ],
    [
     true,
     0
    ]
   ]
  },
  {
   "seq": 5,
   "operation": "check_rule",
   "arguments": {
    "rule": "late"
   },
   "contract_version": "1.0.0",
   "definitions_in_response": [],
   "definitions_by_registry_mapping": [],
   "in_server_log": true,
   "server_log_definitions": null,
   "server_log_time": null,
   "result_rows": null
  },
  {
   "seq": 6,
   "operation": "check_rule",
   "arguments": {
    "rule": "delay"
   },
   "contract_version": "1.0.0",
   "definitions_in_response": [],
   "definitions_by_registry_mapping": [],
   "in_server_log": true,
   "server_log_definitions": null,
   "server_log_time": null,
   "result_rows": null
  },
  {
   "seq": 7,
   "operation": "lookup_definition",
   "arguments": {
    "term": "operations on-time"
   },
   "contract_version": "1.0.0",
   "definitions_in_response": [],
   "definitions_by_registry_mapping": [
    "on_time@1",
    "portal_on_time@1",
    "local_time@1"
   ],
   "in_server_log": true,
   "server_log_definitions": null,
   "server_log_time": null,
   "result_rows": null
  },
  {
   "seq": 8,
   "operation": "lookup_definition",
   "arguments": {
    "term": "late delivery"
   },
   "contract_version": "1.0.0",
   "definitions_in_response": [],
   "definitions_by_registry_mapping": [
    "on_time@1"
   ],
   "in_server_log": true,
   "server_log_definitions": null,
   "server_log_time": null,
   "result_rows": null
  },
  {
   "seq": 9,
   "operation": "compute_metric",
   "arguments": {
    "metrics": [
     "late_deliveries"
    ],
    "end_date": "2026-09-30",
    "start_date": "2026-07-01",
    "where": [
     "delivery__shipper_delayed = true"
    ]
   },
   "contract_version": "1.0.0",
   "definitions_in_response": [],
   "definitions_by_registry_mapping": [
    "on_time@1"
   ],
   "in_server_log": true,
   "server_log_definitions": null,
   "server_log_time": null,
   "result_rows": [
    [
     0
    ]
   ]
  },
  {
   "seq": 10,
   "operation": "lookup_definition",
   "arguments": {
    "term": ""
   },
   "contract_version": "1.0.0",
   "definitions_in_response": [],
   "definitions_by_registry_mapping": [],
   "in_server_log": true,
   "server_log_definitions": null,
   "server_log_time": null,
   "result_rows": null
  }
 ],
 "server_log_lines": 10
}
```

## The three checks (0.02 ms)

```json
{
 "basis_for_served": "Part 3 calls confirmed in Part 3's server log by response ID, mapped through the Part 4 registry at version 1",
 "status": "no_sources_line",
 "cited": [],
 "unregistered": [],
 "cited_not_served": [],
 "served": [
  "delivered_load@1",
  "local_time@1",
  "on_time@1",
  "portal_on_time@1"
 ],
 "served_not_cited": true
}
```

## The registry entries and owners (0.37 ms)

```json
[
 {
  "id": "delivered_load",
  "title": "Delivered load",
  "version": 1,
  "owner": "VP Operations",
  "owner_role": "Runs dispatch, carrier relations and the delivery floor. Decides what counts as a load, a delivery and an on-time delivery, because the customer contracts it signs are measured on them.",
  "where": "data/DEFINITIONS.md#delivered_load",
  "history": [
   {
    "version": 1,
    "effective": "2026-10-09",
    "written_by": "VP Operations",
    "change": "First version: delivered is status DLVD on the final row, dated by arrival at the last stop on the local clock.",
    "source_commit": "dea695c"
   }
  ],
  "metrics_used_in_this_run": {
   "delivered_loads": "Loads delivered: the carrier reported the final delivery. Only real loads count, never test rows or voided rows, and a re-tendered load is delivered once, by the carrier that hauled it. Dated by the calendar day of arrival at the final delivery stop, on the clock at that stop."
  }
 },
 {
  "id": "local_time",
  "title": "Local time",
  "version": 1,
  "owner": "VP Operations",
  "owner_role": "Runs dispatch, carrier relations and the delivery floor. Decides what counts as a load, a delivery and an on-time delivery, because the customer contracts it signs are measured on them.",
  "where": "data/DEFINITIONS.md#local_time",
  "history": [
   {
    "version": 1,
    "effective": "2026-10-09",
    "written_by": "VP Operations",
    "change": "First version: operational dates are local at the facility; compare appointment and arrival on one clock.",
    "source_commit": "dea695c"
   }
  ],
  "metrics_used_in_this_run": {}
 },
 {
  "id": "on_time",
  "title": "On-time delivery (official)",
  "version": 1,
  "owner": "VP Operations",
  "owner_role": "Runs dispatch, carrier relations and the delivery floor. Decides what counts as a load, a delivery and an on-time delivery, because the customer contracts it signs are measured on them.",
  "where": "data/DEFINITIONS.md#on_time",
  "history": [
   {
    "version": 1,
    "effective": "2026-10-09",
    "written_by": "VP Operations",
    "change": "First version: on time at or before the end of the appointment window, local clock; a late load with a shipper-caused delay is left out, neither on time nor late. Names the operations meaning and the portal meaning as not official.",
    "source_commit": "dea695c"
   }
  ],
  "metrics_used_in_this_run": {
   "late_deliveries": "Delivered loads that were late under the official on-time rule: arrival at the final delivery stop after the end of the appointment window, on the facility's local clock. A late load with a delay the shipper caused is left out; it is neither on time nor late."
  }
 },
 {
  "id": "portal_on_time",
  "title": "Portal on-time",
  "version": 1,
  "owner": "Director of Customer Experience",
  "owner_role": "Runs the customer portal. Decides what the portal shows customers, including its own on-time flag.",
  "where": "data/DEFINITIONS.md#portal_on_time",
  "history": [
   {
    "version": 1,
    "effective": "2026-10-09",
    "written_by": "Director of Customer Experience",
    "change": "First version: the portal's flag compares delivery date with the requested date; right only for what customers see in the portal.",
    "source_commit": "dea695c"
   }
  ],
  "metrics_used_in_this_run": {}
 }
]
```

The whole trace took 0.6 ms of plain code, with no model in the loop.
