# Part 3: the context server on Cloud Run, and one service identity per agent.
#
# A separate Terraform root from infra/, with its own state, so that
# `terraform destroy` here removes the Part 3 resources and nothing else:
#
#   - an Artifact Registry repository for the server image
#   - a bucket that stages the build's source
#   - a service account for the server, allowed to read the warehouse and run queries
#   - a service account for the image build
#   - one service account per agent configuration, each allowed to invoke the service
#   - the Cloud Run service itself (second apply, once the image exists)
#
# Nobody else can invoke the service: there is no allUsers or allAuthenticatedUsers
# binding, so Cloud Run refuses any call without an ID token from one of the
# agents' service accounts. Nothing here is a key, a password or a token.

locals {
  services = [
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "iamcredentials.googleapis.com",       # minting ID tokens for the agents' identities
    "cloudresourcemanager.googleapis.com", # project role grants
    "storage.googleapis.com",              # the build staging bucket
  ]
  labels = {
    series = "what-your-agents-dont-know"
    part   = "3"
  }
}

resource "google_project_service" "enabled" {
  for_each = toset(local.services)

  project = var.project_id
  service = each.value

  # Leave the APIs on when this is destroyed, so other work in the project is not broken.
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "tessaway-part3"
  format        = "DOCKER"
  description   = "Context server image for Part 3 of What Your Agents Don't Know."
  labels        = local.labels

  depends_on = [google_project_service.enabled]
}

resource "google_storage_bucket" "build_staging" {
  project                     = var.project_id
  name                        = "${var.project_id}-part3-build"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true
  labels                      = local.labels

  lifecycle_rule {
    condition {
      age = 3
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.enabled]
}

# --- identities -------------------------------------------------------------------

resource "google_service_account" "server" {
  project      = var.project_id
  account_id   = "tw-p3-server"
  display_name = "Part 3 context server"
  description  = "Runs the context server. Reads the warehouse and the semantic layer views; runs queries."
}

resource "google_project_iam_member" "server" {
  for_each = toset(["roles/bigquery.jobUser", "roles/bigquery.dataViewer"])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.server.email}"

  depends_on = [google_project_service.enabled]
}

resource "google_service_account" "builder" {
  project      = var.project_id
  account_id   = "tw-p3-builder"
  display_name = "Part 3 image build"
  description  = "Builds the context server image and pushes it to the Part 3 repository."
}

resource "google_artifact_registry_repository_iam_member" "builder" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.builder.email}"
}

resource "google_storage_bucket_iam_member" "builder" {
  bucket = google_storage_bucket.build_staging.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.builder.email}"
}

resource "google_project_iam_member" "builder_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.builder.email}"

  depends_on = [google_project_service.enabled]
}

resource "google_service_account" "caller" {
  for_each = toset(var.callers)

  project      = var.project_id
  account_id   = "tw-p3-agent-${each.value}"
  display_name = "Part 3 agent: ${each.value}"
  description  = "The identity the ${each.value} agent calls the context server under."
}

# The operator mints each agent's ID token by impersonation. No key file exists.
resource "google_service_account_iam_member" "operator_mints_tokens" {
  for_each = google_service_account.caller

  service_account_id = each.value.name
  role               = "roles/iam.serviceAccountOpenIdTokenCreator"
  member             = "user:${var.operator_email}"
}

# --- the service --------------------------------------------------------------------

resource "google_cloud_run_v2_service" "contract" {
  count = var.image == "" ? 0 : 1

  project             = var.project_id
  name                = "tessaway-context"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.labels

  template {
    service_account                  = google_service_account.server.email
    timeout                          = "300s"
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = 2
    }

    containers {
      image = var.image

      resources {
        limits = {
          cpu    = "2"
          memory = "4Gi"
        }
        cpu_idle          = false
        startup_cpu_boost = true
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "BQ_DATASET"
        value = var.warehouse_dataset
      }
      env {
        name  = "BQ_SEMANTIC_DATASET"
        value = var.semantic_dataset
      }
      env {
        name  = "BQ_LOCATION"
        value = "US"
      }
      # Part 7: which version of a changed definition each request gets
      # (context_server/versions.py). Rolling back is a new revision with this changed.
      env {
        name  = "TESSAWAY_ROUTING"
        value = var.routing
      }

      # The layers load before the server listens: the graph, the rule check and MetricFlow.
      startup_probe {
        initial_delay_seconds = 10
        period_seconds        = 10
        timeout_seconds       = 5
        failure_threshold     = 30
        tcp_socket {
          port = 8080
        }
      }
    }
  }

  depends_on = [google_project_iam_member.server, google_project_service.enabled]
}

resource "google_cloud_run_v2_service_iam_member" "caller_invokes" {
  for_each = var.image == "" ? {} : google_service_account.caller

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.contract[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${each.value.email}"
}
