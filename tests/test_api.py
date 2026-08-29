import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
import boto3
from app.main import app
from app.config import settings

@pytest.fixture
def mock_dynamodb():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName=settings.dynamodb_table,
            KeySchema=[{"AttributeName": "shortCode", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "shortCode", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield table

@pytest.fixture
def client(mock_dynamodb, monkeypatch):
    from app.service import URLService
    monkeypatch.setattr("app.main.service", URLService())
    return TestClient(app)

def test_root_endpoint(client):
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert "endpoints" in data

def test_health_check(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"

def test_create_short_url(client):
    r = client.post("/shorten", json={"url": "https://example.com/article/123"})
    assert r.status_code == 201
    data = r.json()
    assert len(data["short_code"]) == 7

def test_shorten_invalid_url(client):
    r = client.post("/shorten", json={"url": "not-a-valid-url"})
    assert r.status_code == 400
    assert "detail" in r.json()

def test_shorten_missing_payload(client):
    r = client.post("/shorten", json={})
    assert r.status_code == 400
    assert "detail" in r.json()

def test_shorten_ttl_exceeds_max(client):
    r = client.post("/shorten", json={"url": "https://example.com", "ttl_days": 9999})
    assert r.status_code == 400

def test_custom_code_and_duplicate(client):
    r = client.post("/shorten", json={"url": "https://example.com", "custom_code": "mycode"})
    assert r.status_code == 201
    r2 = client.post("/shorten", json={"url": "https://other.com", "custom_code": "mycode"})
    assert r2.status_code == 409

def test_redirect_and_click_count(client):
    r = client.post("/shorten", json={"url": "https://target.com"})
    code = r.json()["short_code"]
    rr = client.get(f"/{code}", follow_redirects=False)
    assert rr.status_code == 307
    assert rr.headers["location"] == "https://target.com/"
    stats = client.get(f"/stats/{code}")
    assert stats.json()["click_count"] == 1

def test_not_found(client):
    assert client.get("/nonexistent", follow_redirects=False).status_code == 404

def test_delete(client):
    r = client.post("/shorten", json={"url": "https://delete.com"})
    code = r.json()["short_code"]
    assert client.delete(f"/{code}").status_code == 200
    assert client.get(f"/{code}", follow_redirects=False).status_code == 410

def test_shorten_invalid_scheme(client):
    r = client.post("/shorten", json={"url": "ftp://example.com"})
    assert r.status_code == 400

def test_shorten_invalid_custom_code(client):
    r = client.post("/shorten", json={"url": "https://example.com", "custom_code": "invalid code!"})
    assert r.status_code == 400

def test_stats_not_found(client):
    assert client.get("/stats/nonexistent").status_code == 404

def test_delete_not_found(client):
    assert client.delete("/nonexistent").status_code == 404

def test_expired_url(client, mock_dynamodb):
    # Insert an expired record directly into DynamoDB
    expired_item = {
        "shortCode": "expired1",
        "originalUrl": "https://expired.com",
        "createdAt": "2020-01-01T00:00:00+00:00",
        "expiresAt": "2020-01-02T00:00:00+00:00",
        "ttl": 1577923200,
        "clickCount": 0,
        "isActive": True,
    }
    mock_dynamodb.put_item(Item=expired_item)
    r = client.get("/expired1", follow_redirects=False)
    assert r.status_code == 410

def test_shorten_reserved_custom_code(client):
    r = client.post("/shorten", json={"url": "https://example.com", "custom_code": "health"})
    assert r.status_code == 400
    assert "reserved" in r.json()["errors"][0]["msg"]

def test_oversized_code_lookup(client):
    huge_code = "a" * 100
    assert client.get(f"/{huge_code}", follow_redirects=False).status_code == 404
    assert client.get(f"/stats/{huge_code}").status_code == 404
    assert client.delete(f"/{huge_code}").status_code == 404
