# Copyright 2026 Robert H. Mowery III
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""What a Part 2 agent is told: the Part 1 instruction, plus one tool per layer.

Part 2 gives the agent the same instruction, schema and SQL tool as Part 1 and
adds one tool for each context layer in the configuration. Two things change in
what the model sees, and nothing else:

    1. one short paragraph per layer tool is inserted into the instruction,
       after the paragraph about the SQL tool;
    2. each layer tool arrives with its own description.

``build_instruction(())`` returns the Part 1 instruction unchanged, and a test
holds that taking the added paragraphs back out gives the Part 1 text exactly.

The descriptions below say what each tool is and how to call it. They are
written from data/DEFINITIONS.md, state no answer to any question, and were
committed before any Part 2 agent ran. Changing a word here changes the
experiment.
"""

from __future__ import annotations

from tessaway.agents import prompt
from tessaway.layers import LAYERS, MAX_LAYER_CALLS, semantic

SEMANTIC_TOOL = "query_metrics"
ONTOLOGY_TOOL = "lookup_ontology"
GRAPH_TOOL = "query_graph"

TOOL_OF_LAYER = {"semantic": SEMANTIC_TOOL, "ontology": ONTOLOGY_TOOL, "graph": GRAPH_TOOL}
LAYER_OF_TOOL = {tool: layer for layer, tool in TOOL_OF_LAYER.items()}

# The paragraph each layer adds to the instruction.
INSTRUCTION_PARAGRAPH = {
    "semantic": (
        f"You also have the {SEMANTIC_TOOL} tool. It queries Tessaway's semantic layer: named"
        " business metrics, each with its official definition, which you can group, filter and"
        f" bound in time. You can call it at most {MAX_LAYER_CALLS} times for a question."
    ),
    "ontology": (
        f"You also have the {ONTOLOGY_TOOL} tool. It looks a term up in Tessaway's business"
        " ontology: what kinds of things exist in the business, how each is defined, and the"
        f" rules that bind it. You can call it at most {MAX_LAYER_CALLS} times for a question."
    ),
    "graph": (
        f"You also have the {GRAPH_TOOL} tool. It runs one read-only SPARQL query at a time"
        " against Tessaway's knowledge graph: the company's actual accounts, carriers, tenders"
        f" and loads, and how they connect. You can call it at most {MAX_LAYER_CALLS} times for"
        " a question."
    ),
}

# Where the added paragraphs go: straight after the paragraph about the SQL tool.
_ANCHOR = "\n\nThese are the tables in the warehouse."

ONTOLOGY_DESCRIPTION = (
    "Looks a term up in Tessaway Freight's business ontology and returns what the ontology"
    " says about it. The ontology says what kinds of things exist in the business (for example"
    " a load, a tender, a customer, a proof of delivery), how each is defined, which rules bind"
    " it, and where the warehouse holds it. Give a word or a phrase as the term. With an empty"
    " term it lists every term in the ontology."
)

GRAPH_DESCRIPTION = """Runs one read-only SPARQL query against Tessaway Freight's knowledge \
graph and returns the rows. The graph holds the company's actual accounts, carriers, tenders \
and loads as nodes, and how they connect as edges. At most 50 rows are returned. The prefixes \
tw:, twd:, rdf:, rdfs: and xsd: are already declared.

Node types: tw:Customer, tw:ShipperSite, tw:BillToParty, tw:Carrier, tw:Tender, tw:Load, \
tw:ProofOfDelivery, tw:Invoice. Some nodes carry a second type: tw:TestRow or tw:VoidedRow on a \
tender; tw:DeliveredLoad, tw:BillableLoad or tw:CanceledLoad on a load.

Edges:
tw:ShipperSite tw:rollsUpTo tw:Customer
tw:Tender tw:shipperSite tw:ShipperSite
tw:Tender tw:billTo tw:BillToParty
tw:Tender tw:carrier tw:Carrier
tw:Tender tw:replaces tw:Tender
tw:Load tw:firstTender tw:Tender
tw:Load tw:finalTender tw:Tender
tw:Load tw:customer tw:Customer
tw:ProofOfDelivery tw:proofFor tw:Tender
tw:Invoice tw:forTender tw:Tender

Values on nodes: rdfs:label is the name of an account or a carrier. tw:accountId, tw:carrierId \
and tw:tenderId are the ids the warehouse uses (acct_id, carr_id, load_id). tw:loadId is the \
load_id of a load's first tender. Tenders have tw:status, tw:isTest and tw:isVoid. Proofs of \
delivery have tw:signed."""


def semantic_description() -> str:
    """Build the metric tool's description from what MetricFlow reports."""
    catalog = semantic.catalog()
    metrics = catalog["metrics"]
    every = {m["name"] for m in metrics}
    lines = [
        "Queries Tessaway Freight's semantic layer and returns the rows. The semantic layer"
        " holds the company's named business metrics. Each metric is worked out the way its"
        " official definition says. Give one or more metric names from the list below. You can"
        " group by dimensions, filter on them, and bound the metric's own time. At most 50 rows"
        " are returned.",
        "",
        "Arguments:",
        "- metrics: one or more metric names.",
        "- group_by: dimension names. To group by time use metric_time__day, metric_time__week,"
        " metric_time__month, metric_time__quarter or metric_time__year.",
        "- where: conditions on dimension names, written as in SQL, for example"
        " tender__carrier_name = 'Some Carrier'. All of them must hold.",
        "- start_date, end_date: the first and last day of the period as YYYY-MM-DD, both"
        " included. They apply to the date each metric says it is dated by.",
        "- order_by: metric or dimension names to sort by. Put - in front of a name to sort"
        " from high to low.",
        "- limit: the most rows to return.",
        "",
        "Metrics:",
    ]
    lines += [f"- {m['name']}: {m['description']}" for m in metrics]
    lines += ["", "Dimensions:"]
    for dimension in catalog["dimensions"]:
        if dimension["type"] == "time":
            continue  # reached through metric_time and the date arguments
        users = sorted(m["name"] for m in metrics if dimension["name"] in m["dimensions"])
        scope = "" if set(users) == every else f" (only with: {', '.join(users)})"
        lines.append(f"- {dimension['name']}{scope}: {dimension['description']}")
    return "\n".join(lines)


def tool_description(layer: str) -> str:
    """Return the description the model reads for a layer's tool."""
    if layer == "semantic":
        return semantic_description()
    return {"ontology": ONTOLOGY_DESCRIPTION, "graph": GRAPH_DESCRIPTION}[layer]


def build_instruction(layers: tuple[str, ...]) -> str:
    """Return the Part 1 instruction with one paragraph added per layer tool."""
    unknown = [layer for layer in layers if layer not in LAYERS]
    if unknown:
        raise ValueError(f"unknown layer(s): {unknown}")
    if prompt.INSTRUCTION.count(_ANCHOR) != 1:
        raise ValueError("the Part 1 instruction no longer has the paragraph the tools follow")
    added = "".join(f"\n\n{INSTRUCTION_PARAGRAPH[layer]}" for layer in LAYERS if layer in layers)
    return prompt.INSTRUCTION.replace(_ANCHOR, added + _ANCHOR)
