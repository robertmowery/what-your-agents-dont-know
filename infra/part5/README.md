# Part 5: the golden-set check as a Cloud Run job

A separate Terraform root with its own state. Apply `infra/` and `infra/part3` first; destroy this root before `infra/part3`.

Nothing here is a key, a password or a token. The job runs as its own service account (`tw-p5-check`) and signs its calls to the context server with an ID token from the metadata server.

## Deploy

```bash
cd infra/part5
cp terraform.tfvars.example terraform.tfvars     # project_id; contract_url from infra/part3; image = ""
terraform init
terraform apply                                  # results bucket, the job's and the scheduler's accounts, grants

# Build the image from the repo root, with the Part 3 repository and build account
cd ../..
gcloud builds submit . --project YOUR_PROJECT \
  --config golden_check/cloudbuild.yaml --ignore-file golden_check/.gcloudignore \
  --substitutions _IMAGE=$(terraform -chdir=infra/part3 output -raw image_repository)/golden-check:v1 \
  --service-account $(terraform -chdir=infra/part3 output -raw builder) \
  --gcs-source-staging-dir gs://$(terraform -chdir=infra/part3 output -raw build_staging_bucket)/source

cd infra/part5
# set image in terraform.tfvars, then
terraform apply                                  # the Cloud Run job and the paused nightly schedule
```

## Run it by hand

```bash
gcloud run jobs execute tessaway-golden-check --project YOUR_PROJECT --region us-central1 --wait \
  --args="--phase,drift,--execution,1" --update-env-vars BQ_DATASET=tessaway_wh_p5
python run_part5.py --pull drift
```

Each execution asks the 24 golden-set questions once, four at a time, and writes `part5/<phase>/e<execution>/` in the results bucket: one run record and one trace per question, and `alert.json` with the alert rule's verdict. `run_part5.py --pull` copies them into `results/part5` with the project and the service URL taken out.

## Leave it running

The schedule `tessaway-golden-check-nightly` exists and is paused. To leave the check running every night in your own project:

```bash
gcloud scheduler jobs resume tessaway-golden-check-nightly --project YOUR_PROJECT --location us-central1
```

or set `paused = false` in `main.tf`. At Part 4's measured cost (about 3.8 cents a question with `gemini-3.8-flash`), one execution of 24 questions is about 90 cents.

## Tear it down

```bash
cd infra/part5 && terraform destroy
cd ../part3 && terraform destroy
```

| Resource | Why |
| --- | --- |
| Cloud Run job `tessaway-golden-check` | One execution runs the golden set once |
| Cloud Scheduler job `tessaway-golden-check-nightly` (paused) | Would start the job every night at 6:15 a.m. ET |
| Service account `tw-p5-check` | The job's identity: Vertex AI user, BigQuery job user and data viewer, Cloud Trace agent, the results bucket, invoker on the context server |
| Service account `tw-p5-scheduler` | The identity the schedule would start the job as |
| Bucket `<project>-part5-check` | Run records, traces and alerts, until they are pulled |
