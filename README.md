# Airbrake Monitoring Portal

Full-stack AI error monitoring portal with AWS Lambda backend and Aurora DSQL database.

---

## Architecture

```
Frontend (React + Vite)
    ↓  HTTPS
AWS Lambda Function URL
https://l7xnpjosjvyrlx55dxrwdvx5g40okeyd.lambda-url.us-east-1.on.aws
    ↓  IAM auth (automatic via execution role)
Aurora DSQL
ezt2bkam5s4kjre73r25easkcu.dsql.us-east-1.on.aws
```

---

## Lambda Deployment (for whoever has AWS access)

### Step 1 — Build the backend

```bash
cd backend
npm install
npm run build
```

### Step 2 — Create the zip

```powershell
# Windows
Compress-Archive -Path dist, node_modules, package.json -DestinationPath lambda-deploy.zip -Force
```

```bash
# Mac/Linux
zip -r lambda-deploy.zip dist/ node_modules/ package.json
```

### Step 3 — Upload to Lambda

```
AWS Console → Lambda → your function → Code → Upload from → .zip file
Select: lambda-deploy.zip
```

### Step 4 — Set Lambda Handler

```
Lambda → Code → Runtime settings → Edit
Handler:  dist/lambda.lambdaHandler
Runtime:  Node.js 20.x
Timeout:  30 seconds
Memory:   512 MB
```

### Step 5 — Set Environment Variables

```
Lambda → Configuration → Environment variables → Edit
```

| Key | Value |
|---|---|
| `DSQL_ENDPOINT` | `ezt2bkam5s4kjre73r25easkcu.dsql.us-east-1.on.aws` |
| `DSQL_REGION` | `us-east-1` |
| `NODE_ENV` | `production` |
| `TEAMS_WEBHOOK_URL` | *(Teams incoming webhook URL)* |

### Step 6 — Grant Lambda permission to Aurora DSQL

```
Lambda → Configuration → Permissions → click Execution role → Add inline policy
```

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dsql:DbConnectAdmin"],
      "Resource": "arn:aws:dsql:us-east-1:850995535850:cluster/ezt2bkam5s4kjre73r25easkcu"
    }
  ]
}
```

Name it: `AuroraDSQLAccess` → Save

### Step 7 — Verify

Test in Lambda console with this event:
```json
{
  "version": "2.0",
  "requestContext": {"http": {"method": "GET", "path": "/api/health"}},
  "rawPath": "/api/health",
  "rawQueryString": ""
}
```

Expected: `{"statusCode": 200, "body": "{\"status\":\"ok\",...}"}`

---

## Frontend Deployment

The frontend build is pre-configured to call the Lambda URL.

```bash
cd frontend
npm install
npm run build
# Upload frontend/dist/ to S3 bucket: airbrake
aws s3 sync dist/ s3://airbrake --delete
```

Frontend URL: `http://airbrake.s3-website-us-east-1.amazonaws.com`

---

## Local Development

```bash
# Backend (connects to local PostgreSQL — swap DSQL_ENDPOINT in .env for Aurora DSQL)
cd backend
cp .env.example .env   # fill in your values
npm install
npm run dev            # starts on http://localhost:3001

# Frontend
cd frontend
npm install
npm run dev            # starts on http://localhost:3000 (proxies /api to Lambda)
```

---

## Key API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/projects` | List all projects |
| GET | `/api/projects/:name/logs` | Project detail + logs |
| GET | `/api/dashboard/top-projects` | Top 10 most used |
| GET | `/api/dashboard/today-errors` | Today's errors |
| GET | `/api/breaks/grouped` | Grouped error breaks |
| GET | `/api/alert-rules` | Alert rules list |
| POST | `/api/ingest/log` | Ingest a log row |
| POST | `/api/ingest/error` | Ingest an error row |

Full API docs: `https://l7xnpjosjvyrlx55dxrwdvx5g40okeyd.lambda-url.us-east-1.on.aws/api/docs`

---

## Aurora DSQL Tables (already created)

- `tand_f_rubriq_processing`
- `language_quality_score`

Both tables have the schema:
```sql
id uuid, project_name text, file_name text, timestamp timestamptz,
success_count int, failure_count int, error text, error_detail text,
error_hash text, error_status text, word_count int, file_type text,
input_tokens int, output_tokens int, calculated_cost numeric,
llm_usage text, resolved_at timestamp, reopened_at timestamp
```
