import concurrent.futures
import json
import os
import statistics
import time
from datetime import datetime, timezone
import requests

BASE_URL = os.getenv("LOAD_TEST_URL", "https://4ilud0m56g.execute-api.us-east-1.amazonaws.com/Prod").rstrip("/")
NUM_REQUESTS = int(os.getenv("NUM_REQUESTS", "100"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "10"))

def create_url():
    payload = {"url": f"https://example.com/page/{time.time_ns()}", "ttl_days": 1}
    try:
        r = requests.post(f"{BASE_URL}/shorten", json=payload, timeout=15)
        if r.status_code == 201:
            return r.json().get("short_code"), True
    except Exception:
        pass
    return None, False

def get_redirect(code):
    try:
        r = requests.get(f"{BASE_URL}/{code}", allow_redirects=False, timeout=15)
        return r.status_code == 307
    except Exception:
        return False

def percentile(values, p):
    values = sorted(values)
    return values[min(int(len(values) * p), len(values) - 1)]

def measure_create():
    latencies, codes = [], []
    successes = 0
    def task():
        start = time.perf_counter()
        code, ok = create_url()
        return (time.perf_counter() - start) * 1000, code, ok
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        for f in concurrent.futures.as_completed([ex.submit(task) for _ in range(NUM_REQUESTS)]):
            latency, code, ok = f.result()
            latencies.append(latency)
            if ok:
                successes += 1
                codes.append(code)
    return latencies, codes, successes

def measure_redirect(codes):
    latencies = []
    successes = 0
    test_codes = (codes * 5)[:NUM_REQUESTS]
    def task(code):
        start = time.perf_counter()
        ok = get_redirect(code)
        return (time.perf_counter() - start) * 1000, ok
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        for f in concurrent.futures.as_completed([ex.submit(task, c) for c in test_codes]):
            latency, ok = f.result()
            latencies.append(latency)
            if ok:
                successes += 1
    return latencies, successes

def print_stats(name, latencies, successes, total):
    rate = (successes / total) * 100 if total else 0
    print(f"\n=== {name} ===")
    print(f"Requests: {total}")
    print(f"Concurrency: {CONCURRENCY}")
    print(f"Success Rate: {rate:.1f}%")
    print(f"Average Latency: {statistics.mean(latencies):.2f} ms")
    print(f"P50 Latency: {statistics.median(latencies):.2f} ms")
    print(f"P95 Latency: {percentile(latencies, .95):.2f} ms")
    print(f"P99 Latency: {percentile(latencies, .99):.2f} ms")

if __name__ == "__main__":
    print(f"Target: {BASE_URL}")
    print(f"Starting at {datetime.now(timezone.utc).isoformat()} with {NUM_REQUESTS} requests, concurrency {CONCURRENCY}...")
    creates, codes, create_successes = measure_create()
    print_stats("Load Test: POST /shorten", creates, create_successes, len(creates))
    if codes:
        redirects, redirect_successes = measure_redirect(codes)
        print_stats("Load Test: GET /{code} (Redirect)", redirects, redirect_successes, len(redirects))
        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "base_url": BASE_URL,
            "concurrency": CONCURRENCY,
            "create": {
                "count": len(creates),
                "success_rate": f"{(create_successes / len(creates)) * 100:.1f}%",
                "mean_ms": round(statistics.mean(creates), 2),
                "p50_ms": round(percentile(creates, .50), 2),
                "p95_ms": round(percentile(creates, .95), 2),
                "p99_ms": round(percentile(creates, .99), 2),
            },
            "redirect": {
                "count": len(redirects),
                "success_rate": f"{(redirect_successes / len(redirects)) * 100:.1f}%",
                "mean_ms": round(statistics.mean(redirects), 2),
                "p50_ms": round(percentile(redirects, .50), 2),
                "p95_ms": round(percentile(redirects, .95), 2),
                "p99_ms": round(percentile(redirects, .99), 2),
            },
        }
        with open("load_test_results.json", "w") as f:
            json.dump(results, f, indent=2)
        print("\nReal load test results saved to load_test_results.json")
