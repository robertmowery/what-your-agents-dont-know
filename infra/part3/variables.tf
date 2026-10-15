variable "project_id" {
  description = "The Google Cloud project the series runs in. The Part 1 and Part 2 setup in infra/ must already be applied."
  type        = string
}

variable "region" {
  description = "Region for the Cloud Run service, its image repository and the build staging bucket."
  type        = string
  default     = "us-central1"
}

variable "operator_email" {
  description = "The person who runs the experiment. They may mint ID tokens for the agents' service accounts, which is how the run script calls the service as each agent."
  type        = string
}

variable "image" {
  description = "The context server image to run. Empty on the first apply: the repository is created, the image is built into it, and a second apply with the image creates the service."
  type        = string
  default     = ""
}

variable "min_instances" {
  description = "Instances kept warm. 1 during the runs, so no question waits for the layers to load."
  type        = number
  default     = 1
}

variable "callers" {
  description = "One service identity per agent configuration that may call the contract."
  type        = list(string)
  default     = ["available", "routed", "claude"]
}
