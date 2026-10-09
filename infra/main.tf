# The Google Cloud landing zone for the series.
#
# What this creates:
#   - the two APIs the code uses, switched on: BigQuery and Vertex AI
#   - one BigQuery dataset, private to the project's owners
#   - optionally, read-only access for the people named in reader_emails
#
# What it leaves to scripts in the repo, because they need the code:
#   - generating and loading the data: python -m tessaway.warehouse.load
#
# Nothing here is public, and nothing here is a key, a password or a token.
# `terraform destroy` removes the dataset and everything in it.

locals {
  services = [
    "bigquery.googleapis.com",   # the warehouse
    "aiplatform.googleapis.com", # Gemini and Claude through Vertex AI
  ]

  # Everything a reader needs to run the agents, and nothing else. None of
  # these roles can change or delete data.
  reader_project_roles = [
    "roles/bigquery.jobUser", # run queries, billed to this project
    "roles/aiplatform.user",  # call models through Vertex AI
  ]

  reader_grants = {
    for pair in setproduct(var.reader_emails, local.reader_project_roles) :
    "${pair[0]}/${pair[1]}" => { email = pair[0], role = pair[1] }
  }
}

resource "google_project_service" "enabled" {
  for_each = toset(local.services)

  project = var.project_id
  service = each.value

  # Leave the APIs on when this is destroyed, so other work in the project is not broken.
  disable_on_destroy = false
}

resource "google_bigquery_dataset" "warehouse" {
  project       = var.project_id
  dataset_id    = var.dataset_id
  location      = var.bq_location
  friendly_name = "Tessaway Freight warehouse (fictional)"
  description   = "Synthetic data for the article series What Your Agents Don't Know. Tessaway Freight is a fictional company."

  # The data is rebuilt from a fixed seed, so destroy may remove the tables.
  delete_contents_on_destroy = true

  # Access is listed in full, so the dataset does not inherit the broad
  # defaults BigQuery would otherwise add. Owners manage and load the data.
  access {
    role          = "OWNER"
    special_group = "projectOwners"
  }

  # Readers can query the tables. They cannot change or delete them.
  dynamic "access" {
    for_each = toset(var.reader_emails)
    content {
      role          = "READER"
      user_by_email = access.value
    }
  }

  labels = {
    series = "what-your-agents-dont-know"
    data   = "synthetic"
  }

  depends_on = [google_project_service.enabled]
}

# Only evaluated when reader_emails is not empty. Granting project roles needs
# the Cloud Resource Manager API; see the README.
resource "google_project_iam_member" "readers" {
  for_each = local.reader_grants

  project = var.project_id
  role    = each.value.role
  member  = "user:${each.value.email}"
}
