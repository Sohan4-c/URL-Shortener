# AWS Serverless URL Shortener

A high-performance, production-ready serverless URL shortening and redirection engine built with FastAPI, AWS Lambda, Amazon API Gateway, and Amazon DynamoDB, fully managed and deployed via AWS SAM.

---

## 🏛️ Architecture

```
Client / Browser
      │
      ▼
Amazon API Gateway (REST API - Regional)
      │
      ▼
AWS Lambda (Python 3.11 + FastAPI + Mangum)
      │
      ▼
Amazon DynamoDB (On-Demand / Pay-per-request)
```

- **Redirect (Hot Path)**: Single-digit millisecond DynamoDB `GetItem` using `shortCode` as the Hash Partition Key. Avoids table scans entirely.
- **Dynamic URL Resolution**: Lambda inspects API Gateway request context dynamically to return the correct deployed domain prefix without circular CloudFormation dependencies.
- **Dual-Layer Expiration**: Combines DynamoDB native Time-to-Live (TTL) for eventual storage reclamation with application-level `expiresAt` validation to ensure expired links immediately stop redirecting.
- **Atomic Click Tracking**: Atomic `UpdateItem` click counting with `ADD` expressions so reads and redirects remain fast and lock-free.

---

## 🛠️ Tech Stack

- **Runtime**: Python 3.11
- **Framework**: FastAPI + Mangum (ASGI adapter for AWS Lambda)
- **Infrastructure as Code**: AWS Serverless Application Model (AWS SAM) / CloudFormation
- **Database**: Amazon DynamoDB (Pay-per-request billing, SSE encryption, Point-in-Time Recovery, TTL enabled)
- **API Management**: Amazon API Gateway REST API with stage deployment
- **Security & IAM**: Principle of least-privilege IAM execution roles (`DynamoDBCrudPolicy` scoped strictly to the target table)
- **Validation**: Pydantic v2 + Pydantic Settings
- **Testing**: Pytest, Moto (mocked AWS DynamoDB), HTTPX

---

## ✨ Features

- ⚡ **Base62 Collision-Resistant Encoding**: Cryptographically generated 7-character URL-safe tokens (yielding ~3.5 trillion unique combinations).
- 🏷️ **Custom Aliases**: Supports custom short URLs with duplicate validation.
- 🛡️ **DynamoDB Conditional Writes**: `attribute_not_exists(shortCode)` prevents race conditions and overwrites.
- ⏳ **Configurable TTL & Dual Expiration**: Automatic background cleanup via DynamoDB TTL + instant manual expiration check.
- 📊 **Analytics & Metrics**: Real-time click counting and metadata inspection.
- 🗑️ **Soft Deletion**: Immediate link deactivation returning HTTP `410 Gone`.
- 🩺 **Health & Root Endpoints**: Monitoring endpoint (`/health`) and service discovery root route (`/`).
- 🧪 **Comprehensive Mocked Test Suite**: 100% offline unit and integration testing via Moto.

---

## 📡 API Reference

### 1. Root & Discovery
`GET /`

**Response (`200 OK`)**:
```json
{
  "service": "AWS Distributed URL Shortener",
  "version": "1.0.0",
  "status": "healthy",
  "endpoints": {
    "health": "GET /health",
    "shorten": "POST /shorten",
    "redirect": "GET /{short_code}",
    "stats": "GET /stats/{short_code}",
    "delete": "DELETE /{short_code}",
    "docs": "GET /docs"
  }
}
```

---

### 2. Health Check
`GET /health`

**Response (`200 OK`)**:
```json
{
  "status": "healthy",
  "timestamp": "2026-08-29T12:00:53.918682+00:00"
}
```

---

### 3. Create Short URL
`POST /shorten`

**Request Body**:
```json
{
  "url": "https://example.com/long-url-article",
  "custom_code": "my-article",
  "ttl_days": 30
}
```
*(Note: `custom_code` and `ttl_days` are optional)*

**Response (`201 Created`)**:
```json
{
  "short_code": "7XnPNUP",
  "short_url": "https://<api-id>.execute-api.us-east-1.amazonaws.com/Prod/7XnPNUP",
  "original_url": "https://example.com/long-url-article",
  "expires_at": "2026-09-28T12:00:54.620902Z"
}
```

**Validation Error (`400 Bad Request`)**:
```json
{
  "detail": "Invalid request",
  "errors": [
    {
      "type": "url_parsing",
      "loc": ["body", "url"],
      "msg": "Input should be a valid URL"
    }
  ]
}
```

---

### 4. Redirect
`GET /{short_code}`

- Returns `307 Temporary Redirect` with `Location` header set to the destination URL.
- Returns `404 Not Found` if the code does not exist.
- Returns `410 Gone` if the link has expired or been soft-deleted.

---

### 5. Statistics
`GET /stats/{short_code}`

**Response (`200 OK`)**:
```json
{
  "short_code": "7XnPNUP",
  "original_url": "https://example.com/long-url-article",
  "click_count": 142,
  "created_at": "2026-08-29T12:00:54.621101Z",
  "expires_at": "2026-09-28T12:00:54.620902Z",
  "is_active": true
}
```

---

### 6. Soft Delete
`DELETE /{short_code}`

**Response (`200 OK`)**:
```json
{
  "short_code": "7XnPNUP",
  "deleted": true
}
```

---

## 💻 Local Development & Setup

### Prerequisites
- Python 3.11+
- AWS CLI & AWS SAM CLI (optional for local running, required for cloud deployment)

### 1. Clone & Set Up Environment

**Windows PowerShell**:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

**Linux / macOS**:
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

### 2. Run Test Suite
Tests run completely offline using Moto to mock DynamoDB:
```bash
python -m pytest -v
```

### 3. Run Locally with Uvicorn
```bash
uvicorn app.main:app --reload --port 8000
```
Interactive Swagger documentation will be available at `http://localhost:8000/docs`.

---

## 🚀 AWS Deployment (SAM)

1. **Validate Template**:
   ```bash
   sam validate --lint
   ```

2. **Build Serverless Package**:
   ```bash
   sam build
   ```

3. **Deploy Stack**:
   ```bash
   sam deploy --no-confirm-changeset
   ```

After deployment, check CloudFormation outputs for the `ApiUrl`:
```bash
aws cloudformation describe-stacks --stack-name url-shortener --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text
```

---

## 🔬 System Design & Engineering Decisions

1. **Why DynamoDB Point Lookups?**
   Point lookups via `GetItem` on the partition key (`shortCode`) execute in single-digit milliseconds and have an O(1) time complexity. Table scans are completely eliminated.

2. **Conditional Writes for Concurrency**:
   Even with cryptographic pseudo-random generation, collisions can theoretically occur under high write concurrency. Using DynamoDB `ConditionExpression="attribute_not_exists(shortCode)"` guarantees uniqueness at the storage level without distributed locking.

3. **Why Dual-Layer Expiration (TTL + App Layer)?**
   DynamoDB TTL removes expired items asynchronously, typically within 48 hours of expiration. Relying solely on TTL would allow users to access expired links during this cleanup window. Storing an explicit ISO timestamp (`expiresAt`) and validating it on redirect ensures strict, immediate expiration semantics.

4. **Circular Dependency Resolution**:
   In AWS SAM, referencing `ServerlessRestApi` inside the Lambda function's environment variables creates a circular dependency. Rather than hardcoding stage URLs or passing static domains, the service extracts the request host and stage context dynamically via ASGI headers (`requestContext`, `x-forwarded-host`, and `x-forwarded-proto`), allowing seamless portability between custom domains, API Gateway stages, and localhost.
