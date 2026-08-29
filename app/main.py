import logging
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from mangum import Mangum

from .config import settings
from .models import ShortenRequest, ShortenResponse, StatsResponse, DeleteResponse
from .service import URLService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("url_shortener")

app = FastAPI(title="AWS Distributed URL Shortener", version="1.0.0")
service = URLService()

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = [
        {
            "loc": list(err.get("loc", [])),
            "msg": str(err.get("msg", "")),
            "type": err.get("type", ""),
        }
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=400,
        content={"detail": "Invalid request", "errors": errors},
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"action=ERROR path={request.url.path} error={str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

@app.get("/")
def root():
    return {
        "service": "AWS Distributed URL Shortener",
        "version": "1.0.0",
        "status": "healthy",
        "endpoints": {
            "health": "GET /health",
            "shorten": "POST /shorten",
            "redirect": "GET /{short_code}",
            "stats": "GET /stats/{short_code}",
            "delete": "DELETE /{short_code}",
            "docs": "GET /docs",
        },
    }

@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

def get_base_url(request: Request) -> str:
    if settings.base_url and "localhost" not in settings.base_url:
        return settings.base_url.rstrip("/")

    aws_event = request.scope.get("aws.event", {})
    if aws_event:
        proto = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
        stage = aws_event.get("requestContext", {}).get("stage", "")
        stage_path = f"/{stage}" if stage and stage != "$default" else ""
        if host:
            return f"{proto}://{host}{stage_path}".rstrip("/")

    if settings.base_url:
        return settings.base_url.rstrip("/")

    return str(request.base_url).rstrip("/")

@app.post("/shorten", response_model=ShortenResponse, status_code=201)
def shorten(payload: ShortenRequest, request: Request):
    if len(str(payload.url)) > settings.max_url_length:
        raise HTTPException(status_code=400, detail="URL is too long")
    if payload.ttl_days and payload.ttl_days > settings.max_ttl_days:
        raise HTTPException(status_code=400, detail="TTL exceeds maximum")
    try:
        item = service.create(str(payload.url), payload.custom_code, payload.ttl_days)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=500, detail="Unable to create short URL")
    base_url = get_base_url(request)
    logger.info(f"action=CREATE short_code={item['shortCode']} custom={bool(payload.custom_code)} ttl_days={payload.ttl_days}")
    return ShortenResponse(
        short_code=item["shortCode"],
        short_url=f"{base_url}/{item['shortCode']}",
        original_url=item["originalUrl"],
        expires_at=datetime.fromisoformat(item["expiresAt"]),
    )

@app.get("/stats/{code}", response_model=StatsResponse)
def stats(code: str):
    if len(code) > 64:
        raise HTTPException(status_code=404, detail="Short URL not found")
    data = service.stats(code)
    if not data:
        raise HTTPException(status_code=404, detail="Short URL not found")
    logger.info(f"action=STATS short_code={code} clicks={data['click_count']}")
    return data

@app.delete("/{code}", response_model=DeleteResponse)
def delete(code: str):
    if len(code) > 64:
        raise HTTPException(status_code=404, detail="Short URL not found")
    item = service.delete(code)
    if not item:
        raise HTTPException(status_code=404, detail="Short URL not found")
    logger.info(f"action=DELETE short_code={code}")
    return {"short_code": code, "deleted": True}

@app.get("/{code}", include_in_schema=False)
def redirect(code: str):
    if len(code) > 64:
        raise HTTPException(status_code=404, detail="Short URL not found")
    target, status = service.redirect(code)
    if status == 404:
        raise HTTPException(status_code=404, detail="Short URL not found")
    if status == 410:
        raise HTTPException(status_code=410, detail="Short URL expired or deleted")
    logger.info(f"action=REDIRECT short_code={code} status={status}")
    return RedirectResponse(url=target, status_code=status)

handler = Mangum(app)
