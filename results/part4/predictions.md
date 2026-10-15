# Part 4 predictions

Written on 2026-10-13, before any Part 4 agent run, and committed before the smoke test and the first scored run. Each prediction states the rule it is tested by. `run_part4.py` writes the numbers each rule reads into `results/part4/summary.json`; `results/part4/summary.md` reports, prediction by prediction, whether it held. A prediction that fails is reported as failed; none is reworded after the runs.

The design is the revision Robert approved on 2026-10-13 (`workflow/briefs/checks/part-4-check.md`).

## What runs

- **The registry.** `data/definition_registry.json`: the ten definitions of `data/DEFINITIONS.md`, each with its id, version 1, an owner and a history. Owners are fictional roles at Tessaway Freight: the VP Operations owns `load`, `delivered_load`, `on_time` and `local_time`; the Controller owns `billable`, `revenue`, `margin` and `currency`; the VP Account Management owns `customer`; the Director of Customer Experience owns `portal_on_time`. Every ontology term, metric and rule the contract can serve belongs to exactly one definition (`tests/test_registry.py`).
- **The contract, 2.0.0.** Part 3's server and four operations. Every response now lists the definitions it served, each with id, version and owner, and the server's log line for the call names them as `id@version`. What a response served: the definitions a lookup matched (not the full term list it returns when nothing matches), the metrics computed, the rules matched, the kinds of the entities resolved. A response that ended in an error served nothing. Major version, by the rule in `context_server/contract.py`: every operation now returns something it did not.
- **The agent.** Part 3's (Google ADK 2.11.0, `gemini-3.8-flash`), with Part 3's instruction word for word plus one paragraph (`tessaway/agents/provenance_prompt.py`): before the `ANSWER:` line, write `SOURCES: [{"id": ..., "version": ...}]` naming the definitions the answer relies on, or `SOURCES: []`.
- **Two configurations, three runs per question.**
  - **available**: the contract and the SQL tool, the 24 Part 1 questions, 72 runs. Part 5 reuses this run as its baseline.
  - **routed_holdout**: the contract only, the 12 held-out questions, 36 runs.
- **Scoring**: the Part 1 scorer, unchanged. It reads the last `ANSWER:` line; the `SOURCES:` line sits above it.

## How traceability is decided

By code, in `tessaway/traceability.py`, with no model in the loop. A run is **traceable** when all three hold:

1. the reply's last `SOURCES:` line names at least one definition id and version;
2. every id and version named exists in the registry, with an owner;
3. the server's call log, read back from Cloud Logging, shows every one of them served at that version in that run (log lines matched to the run by the run ID the agent sent with each call).

Every other run gets one status: `no_sources_line`, `cites_none`, `cites_unregistered` (an id or version the registry does not hold, or one it cannot read as a whole number), or `cites_unserved` (all registered, but something named was not served in that run).

The measures, on the runs on questions that need a definition (every group but lookup) that ended with an answer value (right or confidently wrong):

- **Share traceable**: traceable runs over those runs.
- **Citing without using**: runs that name any definition the server did not serve in that run.
- **Using without citing**: runs in which the server served at least one definition and the reply names none (an empty or missing `SOURCES:` line). Lookup questions are left out of this count.
- **Lookups** (L1 to L6, available only): the right outcome is an answer that cites nothing; reported apart.

The shares over all runs on those questions, declines included, are reported beside them.

## Did asking for a citation cost accuracy?

Answered by P1 and P2: each compares this run's bins with Part 3's run of the same configuration on the same questions (Part 3 available: 72 right, 0 confidently wrong, of 72; Part 3 routed_holdout: 31 right, 2 confidently wrong, 3 declined, of 36). Citations **cost accuracy** if either prediction fails on its accuracy terms.

## The audit example

Fixed now, before any run: the **first confidently wrong Part 4 run**, taking configurations in the order available then routed_holdout, questions in question-file order, trials in ascending order. If no Part 4 run is confidently wrong, the audit is **Part 3's routed_holdout H10, run 0**, labeled in both articles as from Part 3; its served definitions are rebuilt through the Part 4 registry from the calls Part 3 recorded, counting only calls Part 3's server log confirms by response ID. No planted defect. The audit is printed whatever it shows; if the trace ends at a gap, the gap is shown. `audit.md` holds it.

## Predictions

| # | Prediction | Tested by |
| --- | --- | --- |
| P1 | In **available**, asking for a citation does not cost accuracy. | Right in at least 69 of 72 runs and confidently wrong in at most 1 (Part 3: 72 and 0). |
| P2 | In **routed_holdout**, asking for a citation does not cost accuracy, and H11 is still never answered right. | Right in at least 28 of 36, confidently wrong in at most 3 (Part 3: 31 and 2), and H11 right in 0 of 3. |
| P3 | In **available**, most answers that need a definition can be traced. | Share traceable at least 80%. |
| P4 | In **routed_holdout**, most answers can be traced. | Share traceable at least 80%. |
| P5 | Agents over-cite more than they under-cite: the most common miss is naming a definition the server did not serve (for example `delivered_load` beside `on_time`), not leaving out one it did. | Citing without using is greater than using without citing, both configurations together. |
| P6 | In **available**, lookup answers mostly cite nothing. | At least 12 of 18 lookup runs have a `SOURCES:` line that names nothing. |
| P7 | Every contract response carries 2.0.0, a response ID and the definitions field, and the registry maps everything the contract served. | Every recorded response is stamped, every version seen is 2.0.0, no response lacks the definitions field, and no term, metric or rule a response returned is missing from the registry. |
| P8 | The server's call log and the agents' own records agree, including on what was served. | Every call recorded with a response ID is in the server log with the same operation, version and caller; no server line for a run is missing from its record (calls the MCP layer refused before the contract ran are counted apart, as in Part 3); and in every run the definitions the agent's record says it was served equal those the server log says it served. |
| P9 | H10 goes wrong again in **routed_holdout**, and the wrong answers cite the definition that produced them. | H10 confidently wrong in at least 1 of 3 runs, and every such run cites `on_time@1`. |
| P10 | The citation adds little cost. | In **available**, mean cost per question at most $0.0434 (Part 3: $0.0362, plus 20%). |

## What would change the article

- If P1 or P2 fails, asking for a source cost accuracy, and Medium section 9 says so with the numbers.
- If P3 or P4 fails, the headline finding is how far below 100% traceability sits, and the article leads with the misses.
- If P5 fails, the most common miss is the other kind, and section 5 says which.
- If P8 fails, the server's record cannot be trusted as the third check, and the article says so before reporting any traceable share.
- If P9 fails, H10 is answered right this time; the audit still follows the rule above.

## Spend

Planned: 108 runs at Part 3's measured 3.6 cents (available) and 4.2 cents (routed_holdout) per question, plus about 5% for the citation, plus a smoke test of 4 runs: about $4.60 of Gemini spend. The run stops if estimated Part 4 Gemini spend reaches $7 (the stop line Robert approved). Cloud Run is deployed from `infra/part3` for the runs and torn down after; its cost is recorded apart as an estimate. No Claude runs in this part.
