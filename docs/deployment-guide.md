# Deployment & Operations Guide — Agent Assurance Laboratory

## 1. Local Development Quickstart

The application can be run locally without any external Google Cloud credentials using the bundled in-process synthetic agent and development mock identity.

### Prerequisites
- Python 3.13+
- pip

### Step-by-Step Instructions
1. **Clone repository & install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment**:
   ```bash
   cp .env.example .env
   # Default settings (ENVIRONMENT=development, AUTH_DISABLED=true) are enabled
   ```

3. **Start the API & Studio**:
   ```bash
   cd backend
   uvicorn app.main:app --reload --port 8000
   ```

4. **Access the application**:
   - Web Studio: `http://127.0.0.1:8000`
   - Interactive Swagger API Documentation: `http://127.0.0.1:8000/docs`
   - Bundled Mock Agent Endpoint: `http://127.0.0.1:8000/v1/agent/run`

5. **Run the test suite**:
   ```bash
   python -m pytest backend/tests/ -v
   ```

---

## 2. Docker & Container Deployment

### Local Multi-Container Run
```bash
docker-compose up --build
```
The application will be accessible on `http://localhost:8000`.

### Building Production Image
```bash
docker build -t europe-west2-docker.pkg.dev/YOUR_PROJECT_ID/assurance/assurance-app:v1.0.0 .
```

---

## 3. Terraform Cloud Infrastructure Provisioning (Doc 2 §2)

### Staging & Production Deployment
1. **Authenticate with Google Cloud**:
   ```bash
   gcloud auth login
   gcloud config set project YOUR_GCP_PROJECT_ID
   ```

2. **Initialize Terraform with Remote GCS State**:
   ```bash
   cd infra/terraform
   terraform init \
     -backend-config="bucket=agent-assurance-tfstate-YOUR_PROJECT" \
     -backend-config="prefix=environments/staging"
   ```

3. **Plan Infrastructure**:
   ```bash
   terraform plan -var-file=terraform.tfvars.example -out=tfplan
   ```

4. **Apply Infrastructure**:
   ```bash
   terraform apply tfplan
   ```

Resources provisioned:
- Cloud Run: `assurance-web` (Public ingress) & `assurance-worker` (Internal only)
- Cloud Storage: Private buckets for `fixtures`, `state`, `evidence`, and `reports` (UBLA + Versioning)
- BigQuery: Append-only analytical dataset `agent_assurance_staging`
- Cloud Tasks: `assurance-run-queue` (Rate limited, bounded 3 retries)
- IAM: Dedicated least-privilege service accounts and Workload Identity Federation
- Secret Manager: Signing secrets and adapter credentials
- Cloud Monitoring: 5xx error alerts and budget caps

---

## 4. CI/CD Release Promotion (Doc 2 §3)

1. **Pull Request**:
   - Automated checks: Python linting, unit & UAT tests, Docker build test, and `terraform validate`.
2. **Merge to Main**:
   - Container image built and tagged with immutable SHA.
   - Automatic deployment to staging environment.
3. **Production Promotion Gate**:
   - The same immutable image digest from staging is promoted directly to production (no rebuild).
   - Requires explicit nominated approver review in GitHub Environment.

---

## 5. Rollback & Emergency Runbooks (Doc 2 §5)

### Rollback Procedure (Cloud Run)
If an unhandled regression or bug is detected in production:
```bash
# Shift 100% of traffic immediately to the previous known-good revision
gcloud run services update-traffic assurance-web-prod \
  --to-revisions=PREVIOUS_REVISION_NAME=100 \
  --region=europe-west2
```

### Emergency Run Suspension (Kill Switch Drill)
If suspicious target behavior or downstream compromise occurs:
1. Navigate to the **System Ops & Kill Switch** tab in the Web Studio (or issue `POST /v1/kill-switch`).
2. Provide incident justification and click **Activate Kill Switch**.
3. All new run requests are immediately suspended; existing evidence remains immutable.
