# Part 4 audit: one wrong answer, followed home

Picked by the rule in `predictions.md`: the first confidently wrong Part 4 run (routed_holdout).

Question H10, run 0, configuration routed_holdout. Run ID `9d3148bf-5090-4369-a872-f20f9b275de7`.

## The answer (0.0 ms)

```json
{
 "question_id": "H10",
 "trial": 0,
 "outcome": "confidently_wrong",
 "answer": "0",
 "gold": 139,
 "run_id": "9d3148bf-5090-4369-a872-f20f9b275de7",
 "final_lines": "Consequently, under the official metric `late_deliveries`, exactly **0** late deliveries in Q3 2026 were the shipper's fault. (Note that while 139 delivered loads physically arrived after the appointment window end due to shipper delays in Q3 2026, none of them are counted as late deliveries under the company's business rules.)\n\nSOURCES: [{\"id\": \"on_time\", \"version\": 1}]\nANSWER: 0"
}
```

## What the answer cites (0.01 ms)

```json
{
 "sources_line": "[{\"id\": \"on_time\", \"version\": 1}]",
 "cited": [
  "on_time@1"
 ]
}
```

## The server's record of the run (0.13 ms)

```json
{
 "contract_calls": [
  {
   "seq": 1,
   "operation": "lookup_definition",
   "arguments": {
    "term": "late delivery"
   },
   "contract_version": "2.0.0",
   "definitions_in_response": [
    "on_time@1"
   ],
   "definitions_by_registry_mapping": [
    "on_time@1"
   ],
   "in_server_log": true,
   "server_log_definitions": [
    "on_time@1"
   ],
   "server_log_time": "2026-10-13T18:39:11.381Z",
   "result_rows": null
  },
  {
   "seq": 2,
   "operation": "lookup_definition",
   "arguments": {
    "term": "shipper delay"
   },
   "contract_version": "2.0.0",
   "definitions_in_response": [
    "on_time@1"
   ],
   "definitions_by_registry_mapping": [
    "on_time@1"
   ],
   "in_server_log": true,
   "server_log_definitions": [
    "on_time@1"
   ],
   "server_log_time": "2026-10-13T18:39:11.374Z",
   "result_rows": null
  },
  {
   "seq": 3,
   "operation": "compute_metric",
   "arguments": {
    "end_date": "2026-09-30",
    "start_date": "2026-07-01",
    "group_by": [
     "delivery__arrived_on_time",
     "delivery__shipper_delayed"
    ],
    "metrics": [
     "delivered_loads",
     "late_deliveries",
     "on_time_loads",
     "on_time_measured_loads"
    ]
   },
   "contract_version": "2.0.0",
   "definitions_in_response": [
    "delivered_load@1",
    "on_time@1"
   ],
   "definitions_by_registry_mapping": [
    "delivered_load@1",
    "on_time@1"
   ],
   "in_server_log": true,
   "server_log_definitions": [
    "delivered_load@1",
    "on_time@1"
   ],
   "server_log_time": "2026-10-13T18:39:17.545Z",
   "result_rows": [
    [
     true,
     false,
     2744,
     0,
     2744,
     2744
    ],
    [
     false,
     true,
     139,
     0,
     0,
     0
    ],
    [
     false,
     false,
     409,
     409,
     0,
     409
    ],
    [
     true,
     true,
     142,
     0,
     142,
     142
    ]
   ]
  },
  {
   "seq": 4,
   "operation": "check_rule",
   "arguments": {},
   "contract_version": "2.0.0",
   "definitions_in_response": [],
   "definitions_by_registry_mapping": [],
   "in_server_log": true,
   "server_log_definitions": [],
   "server_log_time": "2026-10-13T18:39:23.239Z",
   "result_rows": null
  },
  {
   "seq": 5,
   "operation": "lookup_definition",
   "arguments": {},
   "contract_version": "2.0.0",
   "definitions_in_response": [],
   "definitions_by_registry_mapping": [],
   "in_server_log": true,
   "server_log_definitions": [],
   "server_log_time": "2026-10-13T18:39:30.024Z",
   "result_rows": null
  },
  {
   "seq": 6,
   "operation": "compute_metric",
   "arguments": {
    "end_date": "2026-09-30",
    "where": [
     "delivery__arrived_on_time = false",
     "delivery__shipper_delayed = true"
    ],
    "start_date": "2026-07-01",
    "metrics": [
     "delivered_loads"
    ]
   },
   "contract_version": "2.0.0",
   "definitions_in_response": [
    "delivered_load@1"
   ],
   "definitions_by_registry_mapping": [
    "delivered_load@1"
   ],
   "in_server_log": true,
   "server_log_definitions": [
    "delivered_load@1"
   ],
   "server_log_time": "2026-10-13T18:39:55.336Z",
   "result_rows": [
    [
     139
    ]
   ]
  },
  {
   "seq": 7,
   "operation": "compute_metric",
   "arguments": {
    "where": [
     "delivery__shipper_delayed = true"
    ],
    "end_date": "2026-09-30",
    "metrics": [
     "late_deliveries"
    ],
    "start_date": "2026-07-01"
   },
   "contract_version": "2.0.0",
   "definitions_in_response": [
    "on_time@1"
   ],
   "definitions_by_registry_mapping": [
    "on_time@1"
   ],
   "in_server_log": true,
   "server_log_definitions": [
    "on_time@1"
   ],
   "server_log_time": "2026-10-13T18:40:01.287Z",
   "result_rows": [
    [
     0
    ]
   ]
  },
  {
   "seq": 8,
   "operation": "lookup_definition",
   "arguments": {
    "term": "portal"
   },
   "contract_version": "2.0.0",
   "definitions_in_response": [
    "portal_on_time@1"
   ],
   "definitions_by_registry_mapping": [
    "portal_on_time@1"
   ],
   "in_server_log": true,
   "server_log_definitions": [
    "portal_on_time@1"
   ],
   "server_log_time": "2026-10-13T18:41:23.748Z",
   "result_rows": null
  }
 ],
 "server_log_lines": 8
}
```

## The three checks (0.02 ms)

```json
{
 "basis_for_served": "the server log's definitions field",
 "status": "traceable",
 "cited": [
  "on_time@1"
 ],
 "unregistered": [],
 "cited_not_served": [],
 "served": [
  "delivered_load@1",
  "on_time@1",
  "portal_on_time@1"
 ],
 "served_not_cited": false
}
```

## The registry entries and owners (0.41 ms)

```json
[
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
   "on_time_loads": "Delivered loads that arrived at the final delivery stop at or before the end of the appointment window, on the facility's local clock. Arriving early is on time. The top of the official on-time rate.",
   "on_time_measured_loads": "Delivered loads that count in the official on-time rate. A load that arrived late and has a delay the shipper caused is left out. The bottom of the official on-time rate.",
   "late_deliveries": "Delivered loads that were late under the official on-time rule: arrival at the final delivery stop after the end of the appointment window, on the facility's local clock. A late load with a delay the shipper caused is left out; it is neither on time nor late."
  }
 }
]
```

The whole trace took 0.6 ms of plain code, with no model in the loop.
