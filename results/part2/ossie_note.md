# Apache Ossie: what exists on 2026-10-09

The brief asked whether the metric definitions can be exported to Apache Ossie, "if its tooling is ready." Checked on 2026-10-09.

## What exists

- Apache Ossie (incubating) is real. It is the project formerly named Open Semantic Interchange (OSI). The repository is https://github.com/apache/ossie (Apache-2.0); the old `open-semantic-interchange/OSI` address redirects to it.
- It has **no release**. There are no GitHub releases and one tag, `osi-0.1.1-rc1`. Nothing is on PyPI: `apache-ossie` and `apache-ossie-dbt` both return 404, although the converter's README says `pip install apache-ossie-dbt`.
- The repository holds a JSON and YAML specification (`core-spec/`), Python types (`python/`, version `0.2.0.dev0`), a Go command line (`cli/`) and reference converters for about twenty tools, including one for dbt's MetricFlow format (`converters/dbt`, version `0.2.0.dev0`).
- Separately, **dbt-core 1.12.5 writes an OSI document itself**: every `dbt parse` writes `target/osi_document.json` beside `semantic_manifest.json`. That file says `"version": "0.1.1"`, the specification as it stood under the old name.

## What was tried

1. **The released path.** `dbt parse` on this project wrote an OSI 0.1.1 document with 5 datasets, 10 relationships and all 18 metrics. A copy is in `semantic_layer/exports/osi_document.json`. It needs nothing beyond the pinned `dbt-core==1.12.5`.
2. **The unreleased path.** In a throwaway environment, the converter was installed from a checkout of `apache/ossie` at commit `28a91f5` (2026-10-09) and run on this project's `semantic_manifest.json` (`ossie-dbt msi-to-ossie`). It wrote an Ossie `0.2.0.dev0` document with 5 datasets, 4 relationships and 18 metrics, which validates against the repository's `ossie-schema.json`. It warned that three metrics that count rows (`loads_booked`, `delivered_loads`, `portal_shipments`) convert with loss: a count of `SUM(1)` has no column to say which dataset it counts, so converting back to dbt would refuse them.
3. The two outputs are not the same format. dbt's 0.1.1 document does not validate against the 0.2.0.dev0 schema: the newer specification moved the model to the document root.

## What was decided

- Apache Ossie is **not part of the build**. Nothing in `requirements.txt` or `requirements-semantic.txt` depends on it, and it plays no part in the experiment or in any result. There is no release to pin.
- The OSI 0.1.1 export that the pinned dbt-core writes is kept in the repository as a by-product, because it comes from released, installable tooling.
- The unreleased converter's output is described here and not committed.

## What an export carries, and what it does not

Both exports carry the metric names, descriptions, aggregation expressions, the datasets and the joins between them. Neither carries the SHACL rules, the ontology's classes or the knowledge graph. The dbt views that do the row-level work (the last delivery stop, local time, the parent roll-up, currency conversion) appear only as dataset names: the logic inside them does not travel with the export. The `apache/ossie` repository also has an `ontology/` folder; it was not evaluated.
