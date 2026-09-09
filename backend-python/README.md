# Airbrake Backend — Python (Flask + Lambda)

## Structure

```
backend-python/
├── lambda_function.py   ← Lambda entry point (Mangum wraps Flask)
├── app.py               ← All Flask routes (all API endpoints)
├── db.py                ← Aurora DSQL connection via boto3 IAM token
├── teams.py             ← Microsoft Teams webhook notifier
├── alert_engine.py      ← Alert check logic (called by EventBridge)
├── requirements.txt     ← Python dependencies
└── .env                 ← Local dev env vars (never commit)
```

## Lambda settings

| Setting | Value |
|---|---|
| Handler (HTTP) | `lambda_function.lambda_handler` |
| Handler (Alerts) | `lambda_function.alert_handler` |
| Runtime | Python 3.12 |
| Timeout | 30 seconds |
| Memory | 512 MB |

## Lambda environment variables

| Key | Value |
|---|---|
| `DSQL_ENDPOINT` | `ezt2bkam5s4kjre73r25easkcu.dsql.us-east-1.on.aws` |
| `DSQL_REGION` | `us-east-1` |
| `NODE_ENV` | `production` |
| `TEAMS_WEBHOOK_URL` | *(your webhook)* |

## IAM policy for Lambda execution role

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["dsql:DbConnectAdmin"],
    "Resource": "arn:aws:dsql:us-east-1:850995535850:cluster/ezt2bkam5s4kjre73r25easkcu"
  }]
}
```

## Deploy

### Option 1 — Upload zip manually
```bash
pip install -r requirements.txt -t package/
cp *.py package/
cd package && zip -r ../lambda-python.zip .
```
Upload `lambda-python.zip` to Lambda.

### Option 2 — Lambda Layer
Since `psycopg2-binary` is large, add it as a Lambda Layer and only zip your `.py` files.

## Local dev

```bash
pip install -r requirements.txt
python -c "from app import app; app.run(port=3001, debug=True)"
```
