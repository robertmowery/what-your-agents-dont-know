output "dataset" {
  description = "The dataset the load script fills. Set BQ_DATASET in .env to this id."
  value       = google_bigquery_dataset.warehouse.dataset_id
}

output "bq_location" {
  description = "Where the dataset lives. Set BQ_LOCATION in .env to this."
  value       = google_bigquery_dataset.warehouse.location
}
