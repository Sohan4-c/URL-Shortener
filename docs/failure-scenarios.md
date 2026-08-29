# System Failure Scenarios & Mitigations

This document outlines potential failure modes in the AWS Serverless URL Shortener, their observed system behavior, implemented mitigations, and remaining engineering limitations.

---

## 1. DynamoDB Unavailability

* **Scenario**: AWS DynamoDB service disruption or regional network partition.
* **Failure**: Boto3 client operations (`get_item`, `put_item`, `update_item`) raise `EndpointConnectionError` or `ProvisionedThroughputExceededException`.
* **Observed Behavior**: HTTP `500 Internal Server Error` with JSON response `{"detail": "Internal server error"}`. Internal trace logged to CloudWatch; no raw AWS exceptions leaked to user.
* **Mitigation**: Boto3 default retry configuration with exponential backoff and jitter. Global exception handler captures unhandled database exceptions safely.
* **Remaining Limitation**: Multi-region DynamoDB Global Tables are required to withstand a full AWS regional outage.

---

## 2. Lambda Execution Timeout

* **Scenario**: Lambda function exceeds its configured 10-second timeout.
* **Failure**: Lambda runtime terminates execution abruptly.
* **Observed Behavior**: API Gateway returns HTTP `504 Gateway Timeout` to client.
* **Mitigation**: Standard execution duration is 7–35 ms, well below the 10-second ceiling. Database connection clients are cached at module scope across warm invocations. `LambdaErrorAlarm` alerts if timeouts spike.
* **Remaining Limitation**: Client must implement retry with backoff if network jitter stalls Lambda execution.

---

## 3. API Gateway Throttling & Spike Overload

* **Scenario**: Burst traffic exceeds regional account limits (default 10,000 req/s, 5,000 burst).
* **Failure**: API Gateway throttles requests before reaching Lambda.
* **Observed Behavior**: HTTP `429 Too Many Requests`.
* **Mitigation**: `LambdaThrottleAlarm` triggers immediately on throttle metrics. API Gateway stage-level token-bucket throttling protects downstream DynamoDB capacity.
* **Remaining Limitation**: Without an edge caching CDN (CloudFront), all reads hit API Gateway directly.

---

## 4. Duplicate Short URL Creation (Race Condition)

* **Scenario**: Two concurrent requests attempt to create a record with the same custom code (`custom_code: "promo2026"`).
* **Failure**: Simultaneous write race condition.
* **Observed Behavior**: First request receives HTTP `201 Created`. Second request receives HTTP `409 Conflict` (`{"detail": "Short code already exists"}`).
* **Mitigation**: DynamoDB conditional write `attribute_not_exists(shortCode)` evaluates atomically at storage layer. Prevents silent overwrites.
* **Remaining Limitation**: None; conditional write guarantees complete consistency.

---

## 5. Short-Code Collision on Random Generation

* **Scenario**: Cryptographically generated 7-character Base62 code collides with an existing code in database.
* **Failure**: `ConditionalCheckFailedException` on `put_item`.
* **Observed Behavior**: Handled transparently by application retry loop; user receives HTTP `201 Created` with an alternate unique code.
* **Mitigation**: `URLService.create()` catches `ConditionalCheckFailedException` and executes up to 5 automated collision retries with freshly seeded cryptographic tokens.
* **Remaining Limitation**: If all 5 collision retries fail (probability $< 10^{-15}$), returns HTTP `500 Unable to create short URL`.

---

## 6. Accessing an Expired URL

* **Scenario**: User accesses a short URL after its TTL / expiration window has passed, but before the DynamoDB background TTL sweeper deletes the item.
* **Failure**: Inconsistent expiration semantics if relying solely on database TTL.
* **Observed Behavior**: HTTP `410 Gone` with JSON payload `{"detail": "Short URL expired or deleted"}`.
* **Mitigation**: Runtime validation layer compares `expiresAt <= datetime.now(timezone.utc)`. Immediate 410 response guaranteed without waiting for DynamoDB's eventual TTL cleanup.
* **Remaining Limitation**: Expired items consume minimal storage in DynamoDB until the background TTL reaper cleans them up (typically within 48 hours).

---

## 7. Hot Partition Under Extreme Traffic Spike

* **Scenario**: A single viral short link receives 20,000 redirect requests per second.
* **Failure**: Single DynamoDB partition exceeds its 3,000 RCU/sec partition limit, throwing throttles.
* **Observed Behavior**: Transient HTTP `500` or `504` errors for that specific key.
* **Mitigation**: Pay-per-request auto-partitions data. In extreme cases, Amazon CloudFront edge caching or DynamoDB Accelerator (DAX) should be deployed in front of the redirect path.
* **Remaining Limitation**: In the current single-region serverless tier, hot partitions depend on DynamoDB's adaptive capacity.

---

## 8. CloudWatch Logging Ingestion Delay or Failure

* **Scenario**: High-volume traffic causes CloudWatch Logs ingestion throttling.
* **Failure**: Log events delayed or dropped by logging subsystem.
* **Observed Behavior**: Application execution and HTTP responses proceed unaffected (logging failure does not break user requests).
* **Mitigation**: Standard Python stdout/stderr buffering handled asynchronously by the Lambda runtime microVM.
* **Remaining Limitation**: Real-time log inspection may experience 1–5 second propagation latency during peak ingestion.

---

## 9. Malformed or Malicious Client Input

* **Scenario**: Client sends non-HTTP scheme (`ftp://`, `javascript:`), empty payload, or oversized body.
* **Failure**: Client input validation failure.
* **Observed Behavior**: HTTP `400 Bad Request` with structured error breakdown: `{"detail": "Invalid request", "errors": [...]}`.
* **Mitigation**: Pydantic v2 `HttpUrl` validation, regex validation on custom codes, reserved route blacklist (`health`, `shorten`, `stats`), and maximum URL length bounds (2048 characters).
* **Remaining Limitation**: None; invalid requests rejected at ingress before consuming database capacity.
