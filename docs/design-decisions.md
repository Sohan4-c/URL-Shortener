# System Design Decisions & Trade-Offs

This document details the architectural rationale, scaling strategies, resilience measures, and trade-offs made in the AWS Serverless URL Shortener.

---

## 1. Core Architecture Decisions

### Why AWS Lambda?
* **Zero Idle Cost**: A URL shortening service exhibits bursty traffic patterns with long tail latency periods. Serverless execution charges strictly for consumed milliseconds ($0.0000166667 per GB-second) rather than 24/7 provisioned EC2 or container instances.
* **Auto-Scaling**: Lambda scales horizontally from 0 to thousands of concurrent executions instantaneously without load balancer or cluster auto-scaling group warm-up delays.
* **Operational Simplicity**: Operating system patching, runtime maintenance, and compute scaling are offloaded to AWS, allowing focus on business logic.

### Why Amazon API Gateway (REST API)?
* **Managed Edge & Ingress**: Handles HTTPS termination, request validation, stage deployments (`Prod`), and connection multiplexing natively.
* **Throttling & Abuse Prevention**: Features built-in token-bucket rate limiting (account and stage level) to protect downstream Lambda and DynamoDB from traffic spikes and denial-of-service attempts.
* **Native Serverless Integration**: Seamlessly integrates with AWS Lambda via proxy integration, eliminating the need for self-managed reverse proxies like Nginx.

### Why Amazon DynamoDB?
* **Predictable Single-Digit Millisecond Latency**: The primary access pattern of a URL shortener is a key-value point lookup (`GetItem` by `shortCode`). DynamoDB consistently delivers sub-10ms response times at any scale.
* **Serverless On-Demand Capacity (PAY_PER_REQUEST)**: Automatically accommodates unexpected traffic spikes with zero capacity planning or provisioned throughput throttling.
* **Built-in TTL (Time-To-Live)**: Automatically reclaims storage for expired records at zero compute or write cost.

---

## 2. Data Modeling & Concurrency Control

### Why `shortCode` as the Hash Partition Key?
* Point lookups (`GetItem`) execute in $O(1)$ time by hashing the partition key directly to the storage partition hosting the record.
* Uniformly distributed Base62 alphanumeric short codes prevent hot partition hotspots across the DynamoDB storage layer.
* Table scans are strictly avoided, ensuring consistent query latency regardless of table size.

### Why Conditional Writes (`attribute_not_exists`)?
* Even with cryptographically random Base62 tokens ($62^7 \approx 3.52 \text{ trillion}$ combinations), concurrent creation requests could theoretically generate identical codes.
* `ConditionExpression="attribute_not_exists(shortCode)"` guarantees atomicity at the storage engine level. If a duplicate is generated, DynamoDB rejects the write with a `ConditionalCheckFailedException`, triggering the application's automatic retry loop without data corruption.

### Why Application Expiration + DynamoDB TTL (Dual-Layer)?
* **DynamoDB TTL Limitation**: DynamoDB TTL scans and deletes expired records asynchronously in the background, which can take up to 48 hours after the expiration timestamp has passed.
* **Application Truth**: The application checks `expiresAt <= datetime.now(timezone.utc)` on every redirect request. If expired, it immediately returns HTTP `410 Gone`, providing deterministic, instantaneous expiration semantics while letting DynamoDB TTL clean up storage eventually.

### Why Atomic Click Counting?
* Using read-modify-write (`get_item` $\to$ `clicks + 1` $\to$ `put_item`) introduces lost updates under concurrent redirect traffic.
* The application executes an atomic `UpdateItem` with expression `SET clickCount = if_not_exists(clickCount, :zero) + :one`. DynamoDB executes this counter increment atomically on the storage node, ensuring 100% accurate analytics under heavy concurrency without distributed locks.

---

## 3. Scalability & High Traffic Scenarios

### What happens at 10× Traffic?
* **Compute**: AWS Lambda concurrency increases smoothly to match incoming requests.
* **Database**: DynamoDB On-Demand partition throughput scales automatically (each partition supports up to 3,000 read capacity units and 1,000 write capacity units per second).
* **Cost**: Linear increase proportional to requests; no infrastructure changes needed.

### What happens at 100× Traffic?
* **Hot Keys**: If a viral URL experiences tens of thousands of requests per second, a single DynamoDB partition could become a bottleneck (exceeding 3,000 RCU/sec).
* **Mitigation**: Introduce a regional **Amazon CloudFront** distribution or **DynamoDB Accelerator (DAX)** in front of the redirect path to cache the hot `shortCode` $\to$ `originalUrl` mappings at the edge with a 60-second TTL.
* **Throttling**: API Gateway stage throttling caps burst spikes to prevent downstream resource exhaustion.

---

## 4. Resilience & Failure Modes

### What happens if DynamoDB is unavailable?
* Boto3 automatically retries idempotent operations up to 3 times with exponential backoff and jitter.
* If DynamoDB remains unreachable, the global exception handler catches the client error and returns a clean HTTP `500 Internal Server Error` (`{"detail": "Internal server error"}`) without leaking AWS credentials, stack traces, or internal error objects.

### What happens if Lambda times out?
* The Lambda timeout is configured to 10 seconds (our typical execution is <35 ms). If an upstream network hang occurs, API Gateway returns HTTP `504 Gateway Timeout`.
* The `LambdaErrorAlarm` CloudWatch alarm tracks timeout occurrences to notify engineering.

### What happens if the client retries a creation request?
* If a custom code is used, the second request safely returns HTTP `409 Conflict` (`Short code already exists`).
* If a random code was requested, a new unique short code is generated without mutating the previous link.

---

## 5. Cost Breakdown & Drivers

The service operates virtually free for low-to-medium volume, and incurs low costs at scale:

| Service | Free Tier Allowance | Incremental Production Cost |
| :--- | :--- | :--- |
| **AWS Lambda** | 1M free requests/mo + 3.2M sec compute | $0.20 per 1M requests + $0.0000166667/GB-s |
| **Amazon DynamoDB** | 25 GB storage + 25 RCU / 25 WCU | $1.25 per million write requests, $0.25 per million read requests |
| **Amazon API Gateway** | 1M free calls/mo for 12 months | $3.50 per million requests |
| **Amazon CloudWatch** | 5 GB log ingestion + 10 free metric alarms | $0.50 per GB ingested |

**Primary Cost Driver**: Amazon API Gateway request fees dominate serverless costs at high scale ($3.50/million). Placing an **Amazon CloudFront** distribution in front reduces API Gateway hits by 80–90% on read-heavy redirect workloads.
