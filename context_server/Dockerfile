# The context server's image. Build it from the repo root:
#
#   gcloud builds submit --project YOUR_PROJECT --config context_server/cloudbuild.yaml \
#       --substitutions _IMAGE=REGION-docker.pkg.dev/YOUR_PROJECT/REPO/context-server:TAG .
#
# Two Python environments, as on a laptop: one for the server and the layers,
# one (/app/.venv-dbt) for the MetricFlow worker, because dbt-bigquery and the
# rest cannot share one (see requirements-semantic.txt). No key or credential is
# copied in: on Cloud Run the service account signs every call.
FROM python:3.13.4-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false DO_NOT_TRACK=1 HOME=/tmp

WORKDIR /app

COPY requirements-semantic.txt /app/requirements-semantic.txt
RUN python -m venv /app/.venv-dbt \
 && /app/.venv-dbt/bin/pip install -r /app/requirements-semantic.txt

COPY context_server/requirements.txt /app/context_server/requirements.txt
RUN pip install -r /app/context_server/requirements.txt

COPY tessaway /app/tessaway
COPY ontology /app/ontology
COPY semantic_layer /app/semantic_layer
COPY context_server /app/context_server
# Part 4: the definition registry the contract stamps on every response.
COPY data/definition_registry.json /app/data/definition_registry.json

RUN useradd --uid 10001 --no-create-home server && chown -R server /app/semantic_layer
USER server

# dbt parses the project at start, with the project id from the service's
# environment, so the image holds no project id.
CMD ["sh", "-c", "cd /app/semantic_layer && /app/.venv-dbt/bin/dbt parse --profiles-dir . --quiet && cd /app && exec python -m context_server.server"]
