# Lab files for the AWS series

These files are copied out of the posts so you can use them without retyping. The posts explain every one of them, and the lab steps say when to create each. The folder layout mirrors the layout of the `plat-platform` repository you build in Post 15.

| File | Post | Purpose |
|---|---|---|
| `data/make_data.py` | 06 | Generates `events.csv` (5,000 rows plus 50 replayed events and some blanks) |
| `app/app.py`, `app/requirements.txt`, `app/Dockerfile`, `app/.dockerignore` | 09 | The `plat-api` container. Post 20 adds a `/predict` route to `app.py` |
| `k8s/plat-api.yaml` | 12 | Deployment and Service for EKS (replace the placeholders) |
| `lambda/plat-ingest/lambda_function.py` | 13 | S3 / SNS / SQS ingest function |
| `lambda/plat-report/lambda_function.py` | 14 | Scheduled report function |
| `lambda/plat-webhook-echo/lambda_function.py` | 15 | Signed-webhook receiver |
| `infra/cloudformation/bucket.yaml` | 16 | Secure project bucket (also the Service Catalog product) |
| `infra/terraform/bucket/main.tf` | 16 | The same bucket in Terraform |
| `buildspec.yml` | 18 | CodeBuild build instructions |
| `ml/` | 19, 20 | `plat/ml` image: preprocessing, training and serving |
| `scripts/pause-platform.sh`, `scripts/resume-platform.sh` | 22 | Stop and start the billable parts |

Replace account IDs, bucket names, endpoints and ARNs with your own before using anything.
