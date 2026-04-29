import os

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from .routers import inventory, sensors, recipes, pi


def _parse_allowed_origins() -> list[str]:
    raw_value = os.getenv(
        "SMART_PANTRY_CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    return [origin.strip() for origin in raw_value.split(",") if origin.strip()]


def require_api_access(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if os.getenv("SMART_PANTRY_ALLOW_UNAUTHENTICATED_API", "false").lower() == "true":
        return

    expected_token = os.getenv("SMART_PANTRY_INTERNAL_API_TOKEN", "").strip()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal API token is not configured",
        )

    if x_api_key != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )

app = FastAPI(
    title="Central API Server",
    description="Backend Server for Smart Pantry IoT System",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_allowed_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(inventory.router, dependencies=[Depends(require_api_access)])
app.include_router(sensors.router, dependencies=[Depends(require_api_access)])
app.include_router(recipes.router, dependencies=[Depends(require_api_access)])
app.include_router(pi.router, dependencies=[Depends(require_api_access)])

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "api-server"}
