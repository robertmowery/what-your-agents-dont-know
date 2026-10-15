output "dataset" {
  description = "The dataset the load script fills. Set BQ_DATASET in .env to this id."
  value       = google_bigquery_dataset.warehouse.dataset_id
}

output "bq_location" {
  description = "Where the dataset lives. Set BQ_LOCATION in .env to this."
  value       = google_bigquery_dataset.warehouse.location
}

output "semantic_dataset" {
  description = "The dataset dbt builds the semantic layer's views in. Set BQ_SEMANTIC_DATASET in .env to this id."
  value       = google_bigquery_dataset.semantic.dataset_id
}
