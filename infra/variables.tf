variable "project_id" {
  description = "The Google Cloud project to set up. It must already exist and have billing enabled."
  type        = string
}

variable "dataset_id" {
  description = "Id of the BigQuery dataset that holds the fictional Tessaway Freight warehouse."
  type        = string
  default     = "tessaway_wh"
}

variable "bq_location" {
  description = "BigQuery location for the dataset."
  type        = string
  default     = "US"
}

variable "reader_emails" {
  description = "Email addresses of people, other than project owners, who may run the agents. Each gets read-only access to the dataset, permission to run queries, and permission to call models. Empty means nobody is granted access here."
  type        = list(string)
  default     = []
}
