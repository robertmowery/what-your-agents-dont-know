variable "project_id" {
  description = "The Google Cloud project the series runs in. infra/ and infra/part3 must already be applied."
  type        = string
}

variable "region" {
  description = "Region for the job, its results bucket and the schedule. The same as the context server's."
  type        = string
  default     = "us-central1"
}

variable "image" {
  description = "The golden-set check's image. Empty on the first apply: the bucket and accounts are created, the image is built, and a second apply creates the job and the paused schedule."
  type        = string
  default     = ""
}

variable "contract_url" {
  description = "The context server's URL, from `terraform -chdir=infra/part3 output -raw service_url`. Never written to results."
  type        = string
  default     = ""
}

variable "contract_service" {
  description = "The context server's Cloud Run service name (infra/part3)."
  type        = string
  default     = "tessaway-context"
}

variable "warehouse_dataset" {
  description = "The warehouse the job's SQL tool reads by default. Each execution in the article names it explicitly."
  type        = string
  default     = "tessaway_wh"
}

variable "schedule" {
  description = "When the schedule would start the job, in America/New_York. It is created paused."
  type        = string
  default     = "15 6 * * *"
}
