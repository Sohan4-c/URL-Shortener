# System Architecture

## Architecture Diagram

```mermaid
flowchart TD
    subgraph ClientLayer["Client Layer"]
        Browser["Browser / Client App"]
    end

    subgraph Ingress["AWS Edge & Ingress"]
        APIGateway["Amazon API Gateway<br/>(REST API / Regional / Stage: Prod)"]
    end

    subgraph Compute["AWS Compute Layer"]
        Lambda["AWS Lambda Function<br/>(Python 3.11 / 256MB / x86_64)"]
        FastAPI["FastAPI + Mangum<br/>ASGI Application Adapter"]
    end

    subgraph Storage["Database & Storage"]
        DynamoDB[("Amazon DynamoDB Table<br/>PK: shortCode (String)<br/>Billing: PAY_PER_REQUEST<br/>TTL, SSE, PITR Enabled")]
    end

    subgraph Governance["Governance, Security & Observability"]
        IAM["AWS IAM Role<br/>(DynamoDBCrudPolicy + BasicExecution)"]
        CloudWatch["Amazon CloudWatch<br/>(Logs, Metrics, Alarms)"]
        SAM["AWS SAM / CloudFormation<br/>(Infrastructure as Code)"]
    end

    Browser -->|1. HTTPS Request<br/>GET /, POST /shorten, GET /{code}| APIGateway
    APIGateway -->|2. Proxy Payload Event| Lambda
    Lambda -->|3. ASGI Execution| FastAPI
    FastAPI -->|4. GetItem / PutItem / UpdateItem| DynamoDB
    DynamoDB -->|5. Item / Attributes| FastAPI
    FastAPI -->|6. JSON / 307 Redirect Response| Lambda
    Lambda -->|7. Proxy Response| APIGateway
    APIGateway -->|8. HTTP Response / Location Header| Browser

    IAM -.->|Grants Least Privilege| Lambda
    Lambda -.->|Streams Logs & Metrics| CloudWatch
    CloudWatch -.->|Triggers Errors / Throttles Alarms| CloudWatch
    SAM -.->|Provisions & Manages| Ingress
    SAM -.->|Provisions & Manages| Compute
    SAM -.->|Provisions & Manages| Storage
```

---

## Component Breakdown

### 1. Ingress: Amazon API Gateway
* **Protocol**: HTTPS / REST.
* **Stage**: `Prod`.
* **Routing**:
  * `/` $\to$ Service discovery and health documentation.
  * `/{proxy+}` $\to$ Dynamic proxy routes (`/health`, `/shorten`, `/{short_code}`, `/stats/{short_code}`).
* **Security**: Enforces request size limits, connection timeouts, and default stage throttling.

### 2. Compute: AWS Lambda & FastAPI
* **Runtime**: Python 3.11.
* **Adapter**: Mangum transforms API Gateway proxy events into standard ASGI HTTP requests.
* **Framework**: FastAPI provides typed routing, request validation via Pydantic, and automatic Swagger documentation (`/docs`).
* **Connection Pooling**: Boto3 client initialized once at module scope and reused across invocations.

### 3. Storage: Amazon DynamoDB
* **Partition Key**: `shortCode` (String).
* **Billing Mode**: `PAY_PER_REQUEST` (On-Demand capacity).
* **Data Protection**: Server-Side Encryption (SSE) with AWS managed keys + Point-in-Time Recovery (PITR).
* **Automated Cleanup**: Time-To-Live (TTL) attribute on `ttl` epoch timestamp.

### 4. Observability: Amazon CloudWatch
* **Log Group**: `/aws/lambda/url-shortener-api`.
* **Structured Logs**: Emits machine-readable access logs containing `action`, `short_code`, `status`, and `latency`.
* **Metric Alarms**:
  * `LambdaErrorAlarm`: Triggers on $\ge 5$ unhandled errors over 5 minutes.
  * `LambdaThrottleAlarm`: Triggers on $\ge 1$ invocation throttles.
