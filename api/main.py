from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import inventory, sensors, recipes, pi

app = FastAPI(
    title="Central API Server",
    description="Backend Server for Smart Pantry IoT System",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(inventory.router)
app.include_router(sensors.router)

app.include_router(recipes.router)
app.include_router(pi.router)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "api-server"}

print("--- API Registered Routes ---")
for route in app.routes:
    print(f"Registered: {getattr(route, 'path', 'Unknown')}")
