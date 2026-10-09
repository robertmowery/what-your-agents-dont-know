# Cloud setup with Terraform

This folder creates the Google Cloud resources the series uses, in a project you own: two APIs switched on and one private BigQuery dataset.

Nothing here contains a key, a password, or a token. Terraform signs in with your own gcloud login.

## Before you start

- A Google Cloud project with billing enabled.
- [Terraform](https://developer.hashicorp.com/terraform/install) 1.6 or later.
- `gcloud auth application-default login`
- The Service Usage API, which Terraform uses to switch on the others. It is on by default in a new project. If it is not:

  ```bash
  gcloud services enable serviceusage.googleapis.com --project YOUR_PROJECT
  ```

## Set up

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # set project_id
terraform init
terraform plan      # read what it will create
terraform apply
```

Then, from the repo root:

```bash
cp .env.example .env                    # set GOOGLE_CLOUD_PROJECT
python -m tessaway.warehouse.load       # generate the data and load it
```

## What it creates

| Resource | Used in | Costs money |
| --- | --- | --- |
| BigQuery and Vertex AI APIs switched on | Every part | No |
| BigQuery dataset `tessaway_wh` | Every part | Storage and queries; the data is a few megabytes |
| Read access for `reader_emails` (optional) | Every part | No |

## Access

The dataset is private. Its access list is written out in full: project owners, plus anyone you name in `reader_emails`. A reader gets three things and nothing else: read-only access to this dataset, permission to run queries, and permission to call models through Vertex AI. None of those can change or delete data.

Leave `reader_emails` empty if you are the project owner and the only user. If you set it, Terraform grants two project-level roles, and that needs one more API:

```bash
gcloud services enable cloudresourcemanager.googleapis.com --project YOUR_PROJECT
```

The agents can only read. Their one tool dry-runs each statement and refuses anything BigQuery does not classify as a plain `SELECT`. See `tessaway/warehouse/query.py`.

## Claude through Vertex AI

The Claude agent calls Claude through Vertex AI in the same project, so there is no API key. Before it works, someone with access to the project has to enable the Claude models in Model Garden in the Google Cloud console and accept Anthropic's terms there. Terraform cannot do that step. Until it is done, `run_part1.py` reports the Claude configurations as not run and carries on with the others.

## Tear down

```bash
cd infra
terraform destroy
```

This deletes the dataset and its tables. The data is rebuilt from a fixed seed, so nothing is lost. `terraform destroy` leaves the APIs switched on, so it cannot break anything else in the project. Switch them off by hand if you want them off.

## State

Terraform keeps a record of what it made in `terraform.tfstate`, in this folder. That file and `terraform.tfvars` are ignored by git. For a team, keep state in a shared bucket instead of on a laptop.
