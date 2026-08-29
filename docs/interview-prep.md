# Amazon SDE I Interview Preparation Guide

This interview preparation guide covers system design, distributed systems, database internals, cloud security, and behavioral STAR stories specifically based on the **AWS Serverless URL Shortener** project.

---

## 1. Architecture & System Flow

### Q: Walk me through the end-to-end request flow of a redirect.
> **Answer**: 
> 1. A client browser makes an HTTPS request to `https://<api-id>.execute-api.us-east-1.amazonaws.com/Prod/{short_code}`.
> 2. API Gateway validates the request path, terminates TLS, checks stage throttling, and passes the proxy event to AWS Lambda.
> 3. Mangum translates the API Gateway event into an ASGI HTTP request for FastAPI.
> 4. FastAPI routes the request to `redirect(code)`.
> 5. The application calls DynamoDB `GetItem` using `shortCode` as the Hash Partition Key with consistent reads ($O(1)$ point lookup).
> 6. If the item is found, the app validates `isActive == True` and `expiresAt > now`.
> 7. An atomic DynamoDB `UpdateItem` is asynchronously triggered to increment `clickCount` by 1.
> 8. The function returns an HTTP `307 Temporary Redirect` with the `Location` header set to the destination URL.

### Q: Why did you choose Serverless (Lambda + API Gateway + DynamoDB) over EC2/ECS + PostgreSQL?
> **Answer**:
> * **Traffic Profile**: URL shortening is bursty with long idle periods. Serverless costs $0 when idle, whereas EC2 or ECS tasks incur continuous 24/7 provisioned costs.
> * **Operational Overhead**: Serverless offloads OS patching, scaling, and high-availability configuration to AWS.
> * **Access Pattern**: The primary access pattern is a pure key-value point lookup (`shortCode` $\to$ URL), which aligns perfectly with DynamoDB's NoSQL model rather than relational joins.

---

## 2. Database & Data Modeling (DynamoDB)

### Q: What is your partition key and why?
> **Answer**: The partition key is `shortCode` (String). Because URL lookups are key-value point lookups, hashing the `shortCode` allows DynamoDB to immediately route the read request directly to the storage partition hosting the item in single-digit milliseconds.

### Q: Why do you avoid DynamoDB `Scan`?
> **Answer**: A `Scan` examines every single item in the entire table, consuming massive read capacity units (RCUs) and degrading to $O(N)$ latency as the table grows. `GetItem` is $O(1)$ and consumes only 1 RCU per 4 KB read (or 0.5 RCU for eventually consistent reads).

### Q: How do conditional writes prevent race conditions?
> **Answer**: When generating short codes, even random generation could theoretically produce a collision during concurrent creation bursts. We execute `put_item` with `ConditionExpression="attribute_not_exists(shortCode)"`. This condition is evaluated atomically at the DynamoDB storage engine level before committing the write. If a record with that code already exists, DynamoDB throws a `ConditionalCheckFailedException`, allowing the application to safely retry generation without overwriting existing data.

### Q: How does atomic click counting work?
> **Answer**: Rather than reading the item into memory, incrementing the counter, and writing it back (which causes lost updates if two redirects occur simultaneously), we execute DynamoDB `UpdateItem` with the update expression `SET clickCount = if_not_exists(clickCount, :zero) + :one`. DynamoDB executes this counter increment atomically in-place on the storage partition.

### Q: What happens if a single URL goes viral (Hot Partition)?
> **Answer**: A single DynamoDB partition supports up to 3,000 Read Capacity Units (RCUs) per second. If a viral short URL exceeds this throughput, requests to that partition will be throttled. 
> To mitigate this, we would introduce **Amazon CloudFront** edge caching or **DynamoDB Accelerator (DAX)** in front of the redirect path to cache the `shortCode` $\to$ `originalUrl` mapping with a short TTL (e.g. 60 seconds), absorbing 95%+ of the read volume at the edge.

---

## 3. Distributed Systems & Reliability

### Q: Why do you use both application expiration and DynamoDB TTL?
> **Answer**: DynamoDB native TTL deletes expired items in the background asynchronously, but AWS guarantees deletion only within 48 hours. Relying strictly on TTL would allow users to access expired links for up to two days. We check `expiresAt <= now` in the application layer to enforce deterministic, immediate expiration (returning HTTP 410 Gone), while using DynamoDB TTL to reclaim storage space for free eventually.

### Q: What happens if DynamoDB experiences an outage?
> **Answer**: The AWS SDK (Boto3) automatically retries transient errors with exponential backoff and jitter. If DynamoDB remains unavailable, our global exception handler catches the exception and returns a clean, sanitized HTTP `500 Internal Server Error` (`{"detail": "Internal server error"}`) while logging the error to CloudWatch. We do not leak AWS error details or stack traces to clients.

### Q: How would you make URL creation idempotent?
> **Answer**: Currently, if a client submits the same URL twice without a custom code, two distinct short codes are created. To make creation idempotent, we could either:
> 1. Accept a client-supplied `Idempotency-Key` header stored in DynamoDB with a 24-hour TTL.
> 2. Use a SHA-256 hash of the normalized original URL as a Global Secondary Index (GSI) or deterministic seed to look up existing active links before creating a new one.

---

## 4. Performance & Load Testing

### Q: How did you test performance and what were the results?
> **Answer**: We ran a multi-threaded load test (`load_test.py`) hitting the live AWS API Gateway endpoint under concurrency 10:
> * **Success Rate**: 100.0% across all concurrent creation and redirect requests.
> * **End-to-End Latency**: P50 of 347 ms (including cross-country internet roundtrip transit to AWS `us-east-1`).
> * **Compute Execution**: Real Lambda execution duration in CloudWatch logs was 7.45 ms to 34.33 ms with memory usage at 113 MB (out of 256 MB allocated).

---

## 5. Behavioral Stories (Amazon STAR Format)

### Story 1: Solving the Circular Dependency in Infrastructure as Code (Invent & Simplify / Ownership)
* **Situation**: While deploying the application using AWS SAM, we needed the Lambda function to return the full deployed API Gateway URL in the JSON response.
* **Task**: Attempting to inject `!Sub "https://${ServerlessRestApi}..."` into Lambda environment variables caused CloudFormation to fail with a circular dependency error (`URLShortenerFunction` $\leftrightarrow$ `ServerlessRestApi`).
* **Action**: Instead of hardcoding the URL or introducing extra deployment stages, I designed a runtime resolver in the ASGI layer that dynamically inspects the request headers (`x-forwarded-host`, `x-forwarded-proto`, and `requestContext.stage`).
* **Result**: Eliminated the circular dependency completely, and the service now seamlessly adapts whether running on localhost, an API Gateway stage, or a custom domain.

### Story 2: Diagnosing and Fixing API Gateway Root Route 403 (Dive Deep)
* **Situation**: When navigating to the root URL `/Prod/` in the browser, API Gateway returned `{"message":"Missing Authentication Token"}`.
* **Task**: Determine why the root path failed while `/health` and `/shorten` worked.
* **Action**: Dived deep into API Gateway REST API routing mechanics. I discovered that greedy proxy resources (`/{proxy+}`) only match paths with at least one segment after the stage, and do not match the root stage path `/`. I added an explicit `RootEvent` (`Path: /`) to `template.yaml` and implemented a root service discovery handler in `app/main.py`.
* **Result**: The root endpoint now cleanly returns service metadata and health documentation with HTTP 200 OK.
