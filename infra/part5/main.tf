# Part 5: the golden-set check as a Cloud Run job, with a schedule defined and paused.
#
# A separate Terraform root with its own state, applied after infra/part3 (the
# context server, its image repository and its build account) and destroyed
# before it:
#
#   - a bucket where each execution writes its run records, traces and alert
#   - a service account for the job: Gemini on Vertex AI, BigQuery reads and
#     queries, Cloud Trace, the results bucket, and invoking the context server
#   - the Cloud Run job (second apply, once the image exists)
#   - a Cloud Scheduler entry that would start the job every night, created
#     PAUSED: in the article the job is started by hand, three times with the
#     drift in place and once after the fix
#   - a service account the scheduler would start the job as
#
# Nothing here is a key, a password or a token.

locals {
  services = [
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudtrace.googleapis.com",
    "aiplatform.googleapis.com",
    "storage.googleapis.com",
  ]
  labels = {
    series = "what-your-agents-dont-know"
    part   = "5"
  }
  job_name = "tessaway-golden-check"
}

resource "google_project_service" "enabled" {
  for_each = toset(local.services)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_storage_bucket" "results" {
  project                     = var.project_id
  name                        = "${var.project_id}-part5-check"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true
  labels                      = local.labels

  depends_on = [google_project_service.enabled]
}

# --- the job's identity -------------------------------------------------------------

resource "google_service_account" "check" {
  project      = var.project_id
  account_id   = "tw-p5-check"
  display_name = "Part 5 golden-set check"
  description  = "Runs the golden set: asks Gemini, reads the warehouse, calls the context server, writes results and traces."
}

resource "google_project_iam_member" "check" {
  for_each = toset([
    "roles/aiplatform.user",
    "roles/bigquery.jobUser",
    "roles/bigquery.dataViewer",
    "roles/cloudtrace.agent",
    # tessaway.config pins the quota project on every client, which needs this role.
    "roles/serviceusage.serviceUsageConsumer",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.check.email}"

  depends_on = [google_project_service.enabled]
}

resource "google_storage_bucket_iam_member" "check_writes_results" {
  bucket = google_storage_bucket.results.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.check.email}"
}

# The context server from infra/part3 refuses any caller without an invoker grant.
resource "google_cloud_run_v2_service_iam_member" "check_invokes_contract" {
  project  = var.project_id
  location = var.region
  name     = var.contract_service
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.check.email}"
}

# --- the job ------------------------------------------------------------------------

resource "google_cloud_run_v2_job" "check" {
  count = var.image == "" ? 0 : 1

  project             = var.project_id
  name                = local.job_name
  location            = var.region
  deletion_protection = false
  labels              = local.labels

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account = google_service_account.check.email
      timeout         = "3600s"
      max_retries     = 0

      containers {
        image = var.image
        # In the scheduled phase the job names its folder from the UTC date and
        # Cloud Run's execution ID, so every night writes its own results and
        # asks all 24 questions. "--execution 1" is only a default here.
        args = ["--phase", "scheduled", "--execution", "1"]

        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
          }
        }

        env {
          name  = "GOOGLE_CLOUD_PROJECT"
          value = var.project_id
        }
        env {
          name  = "GOOGLE_CLOUD_LOCATION"
          value = "global"
        }
        env {
          name  = "GOOGLE_GENAI_USE_ENTERPRISE"
          value = "TRUE"
        }
        env {
          name  = "BQ_DATASET"
          value = var.warehouse_dataset
        }
        env {
          name  = "BQ_LOCATION"
          value = "US"
        }
        env {
          name  = "CONTRACT_URL"
          value = var.contract_url
        }
        env {
          name  = "RESULTS_BUCKET"
          value = google_storage_bucket.results.name
        }
        env {
          name  = "CLOUD_TRACE"
          value = "1"
        }
        # ADK probes for an mTLS client certificate before each MCP session. On
        # Cloud Run the probe waits about 13 seconds and then fails; the Mac's
        # fails at once. The service is reached over ordinary TLS either way.
        env {
          name  = "GOOGLE_API_USE_CLIENT_CERTIFICATE"
          value = "false"
        }
      }
    }
  }

  depends_on = [google_project_iam_member.check, google_project_service.enabled]
}

# --- the schedule, defined and paused -----------------------------------------------

resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = "tw-p5-scheduler"
  display_name = "Part 5 scheduler"
  description  = "The identity Cloud Scheduler would start the golden-set check as."
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_runs_job" {
  count = var.image == "" ? 0 : 1

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.check[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "nightly" {
  count = var.image == "" ? 0 : 1

  project     = var.project_id
  region      = var.region
  name        = "tessaway-golden-check-nightly"
  description = "Starts the golden-set check every night. Created paused for the article; resume it to leave the check running."
  schedule    = var.schedule
  time_zone   = "America/New_York"
  paused      = true

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.check[0].name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_project_service.enabled]
}
