# Part 3: the context server on Cloud Run

A separate Terraform root from `infra/`, with its own state, so that `terraform destroy` here removes the Part 3 resources and nothing else. Apply `infra/` first.

Nothing here is a key, a password or a token. Terraform signs in with your own gcloud login, and every agent calls the service under its own service account, by an ID token the run script mints by impersonation.

## Deploy

```bash
cd infra/part3
cp terraform.tfvars.example terraform.tfvars        # project_id, operator_email; image = ""
terraform init
terraform apply                                     # repository, bucket, service accounts

# Build the image from the repo root (only the files .gcloudignore lets through are uploaded)
cd ../..
gcloud builds submit . --project YOUR_PROJECT \
  --config context_server/cloudbuild.yaml \
  --substitutions _IMAGE=$(terraform -chdir=infra/part3 output -raw image_repository)/context-server:v1 \
  --service-account $(terraform -chdir=infra/part3 output -raw builder) \
  --gcs-source-staging-dir gs://$(terraform -chdir=infra/part3 output -raw build_staging_bucket)/source

cd infra/part3
# set image in terraform.tfvars to the image above, then
terraform apply                                     # the Cloud Run service and who may invoke it
```

The server loads the knowledge graph, checks every rule against it and starts MetricFlow before it listens: about three and a half minutes on Cloud Run. `min_instances = 1` keeps one instance warm during the runs.

## Check it

```bash
python run_part3.py --check-auth      # no token: refused; forged token: refused; an agent's token: accepted
pytest -m cloud tests/test_part3_cloud.py
```

## What it costs, and tearing it down

One warm instance (2 vCPU, 4 GiB, CPU always allocated) costs roughly $0.20 an hour in us-central1 at list prices, plus a few cents of BigQuery. Tear it down when the runs are done:

```bash
cd infra/part3
terraform destroy
```

That removes the service, the service accounts and their grants, the image repository with its images, and the build staging bucket. The APIs it switched on are left on, as in `infra/`. Cloud Build's own build records and Cloud Logging's log entries are not Terraform resources; logs expire under the project's retention settings.

| Resource | Why |
| --- | --- |
| Cloud Run service `tessaway-context` | Serves the contract over MCP at `/mcp` |
| Service account `tw-p3-server` | The service's identity: BigQuery job user and data viewer |
| Service accounts `tw-p3-agent-available`, `-routed`, `-claude` | One identity per agent configuration; each may invoke the service |
| Service account `tw-p3-builder` | Builds the image and pushes it |
| Artifact Registry repository `tessaway-part3` | Holds the image |
| Bucket `<project>-part3-build` | Stages the build's source; objects expire after three days |
