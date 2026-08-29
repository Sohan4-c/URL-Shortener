# Resume Bullets — AWS Serverless URL Shortener

These bullet points are formulated specifically for an **Amazon SDE I / SDE Intern** application. All metrics and architectural claims are derived strictly from actual implementations, live benchmarks, and verified test results in this repository.

---

## 🎯 Recommended Resume Bullets (Choose 3–4)

### Option 1: Architecture & Serverless Backend
> **Designed and deployed** a serverless URL shortening and analytics platform using **Python 3.11, FastAPI, AWS Lambda, API Gateway, and DynamoDB (On-Demand)**, delivering sub-10ms database point lookups (`GetItem`) and eliminating table scans across the hot redirect path.

### Option 2: Concurrency, Reliability & Data Modeling
> **Architected collision-resistant URL generation** with Base62 tokens (~3.5T keyspace) and enforced concurrency safety using **DynamoDB conditional writes** (`attribute_not_exists`) and **atomic counter updates**, preventing race conditions and lost updates under concurrent redirect traffic.

### Option 3: Performance, Load Testing & Dual-Layer Expiration
> **Engineered dual-layer link expiration** coupling runtime timestamp validation with asynchronous **DynamoDB TTL**; load-tested the live AWS deployment across 200 concurrent requests, achieving a **100% success rate** and **347 ms P50 end-to-end latency** (7–35 ms internal Lambda compute).

### Option 4: Production Observability, CI/CD & Infrastructure as Code
> **Implemented Infrastructure as Code (IaC)** using **AWS SAM**, automated CI quality validation via **GitHub Actions** (17 Pytest/Moto integration tests, cfn-lint, SAM build), and configured CloudWatch metric alarms for real-time error and throttle detection.

---

## 💡 How to Tailor for Amazon Leadership Principles (LPs)

* **Ownership**: "Spearheaded the design of dual-layer expiration semantics, recognizing that eventual DynamoDB TTL cleanup was insufficient for immediate redirect invalidation."
* **Invent and Simplify**: "Resolved circular CloudFormation template dependencies by dynamically resolving request host context at runtime within ASGI middleware."
* **Bias for Action**: "Benchmarked production behavior against live AWS endpoints with concurrent thread-pool load scripts to measure real P50/P95/P99 latency rather than relying on local estimates."
* **Customer Obsession**: "Enforced strict input sanitization and reserved-route namespaces to prevent link collisions and guarantee clean 400/404/410 HTTP client responses."
