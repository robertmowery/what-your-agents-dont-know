# The golden-set check's image (Part 5). Build it from the repo root:
#
#   gcloud builds submit --project YOUR_PROJECT --config golden_check/cloudbuild.yaml \
#       --ignore-file golden_check/.gcloudignore \
#       --substitutions _IMAGE=REGION-docker.pkg.dev/YOUR_PROJECT/REPO/golden-check:TAG .
#
# The same agent code as the Mac runs in Parts 3 and 4, plus the frozen golden
# set, the alert baseline and the tracing packages. No key or credential is
# copied in: on Cloud Run the job's service account signs every call.
FROM python:3.13.4-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HOME=/tmp \
    ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false

WORKDIR /app

COPY requirements.txt /app/requirements.txt
COPY golden_check/requirements.txt /app/golden_check/requirements.txt
RUN pip install -r /app/requirements.txt -r /app/golden_check/requirements.txt

COPY tessaway /app/tessaway
COPY context_server /app/context_server
COPY golden_check /app/golden_check
COPY questions /app/questions
COPY run_part1.py run_part2.py run_part3.py run_part4.py /app/
COPY data/DEFINITIONS.md data/definition_registry.json /app/data/
COPY results/part1/gold_answers.json /app/results/part1/gold_answers.json
COPY results/part5/alert_baseline.json /app/results/part5/alert_baseline.json

RUN useradd --uid 10001 --no-create-home check
USER check

ENTRYPOINT ["python", "-m", "golden_check.job"]
