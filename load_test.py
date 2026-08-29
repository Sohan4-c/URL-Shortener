import concurrent.futures
import json
import statistics
import time
from datetime import datetime, timezone
import requests

BASE_URL = "http://localhost:8000"
NUM_REQUESTS = 500
CONCURRENCY = 20

def create_url():
    payload = {"url": f"https://example.com/page/{time.time_ns()}", "ttl_days": 1}
    r = requests.post(f"{BASE_URL}/shorten", json=payload, timeout=10)
    return r.json()["short_code"] if r.status_code == 201 else None

def get_redirect(code):
    return requests.get(f"{BASE_URL}/{code}", allow_redirects=False, timeout=10).status_code

def percentile(values, p):
    values = sorted(values)
    return values[min(int(len(values) * p), len(values) - 1)]

def measure_create():
    latencies, codes = [], []
    def task():
        start = time.perf_counter()
        code = create_url()
        return (time.perf_counter() - start) * 1000, code
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        for f in concurrent.futures.as_completed([ex.submit(task) for _ in range(NUM_REQUESTS)]):
            latency, code = f.result()
            latencies.append(latency)
            if code:
                codes.append(code)
    return latencies, codes

def measure_redirect(codes):
    latencies = []
    test_codes = (codes * 5)[:NUM_REQUESTS]
    def task(code):
        start = time.perf_counter()
        status = get_redirect(code)
        return (time.perf_counter() - start) * 1000, status
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        for f in concurrent.futures.as_completed([ex.submit(task, c) for c in test_codes]):
            latency, _ = f.result()
            latencies.append(latency)
    return latencies

def print_stats(name, latencies):
    print(f"\n=== {name} ===")
    print(f"Total: {len(latencies)}")
    print(f"Min: {min(latencies):.2f} ms")
    print(f"Mean: {statistics.mean(latencies):.2f} ms")
    print(f"Median/P50: {statistics.median(latencies):.2f} ms")
    print(f"P95: {percentile(latencies, .95):.2f} ms")
    print(f"P99: {percentile(latencies, .99):.2f} ms")

if __name__ == "__main__":
    print("Starting:", datetime.now(timezone.utc).isoformat())
    creates, codes = measure_create()
    print_stats("POST /shorten", creates)
    if codes:
        redirects = measure_redirect(codes)
        print_stats("GET /{code}", redirects)
        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "base_url": BASE_URL,
            "concurrency": CONCURRENCY,
            "create": {"count": len(creates), "p50_ms": percentile(creates,.50), "p95_ms": percentile(creates,.95), "p99_ms": percentile(creates,.99)},
            "redirect": {"count": len(redirects), "p50_ms": percentile(redirects,.50), "p95_ms": percentile(redirects,.95), "p99_ms": percentile(redirects,.99)},
        }
        with open("load_test_results.json", "w") as f:
            json.dump(results, f, indent=2)
        print("Results saved to load_test_results.json")
