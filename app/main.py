# Heimdall API — entrypoint FastAPI
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .routes import auth_routes, kpi_routes

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Heimdall API", version="0.1.0",
              description="Analítica de Low Fuel Motorsport — todo lo que LFM no te muestra")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(kpi_routes.router)


@app.on_event("startup")
def on_startup():
    init_db()
    logging.getLogger("heimdall").info("Heimdall API arrancada")


@app.get("/health")
def health():
    return {"status": "ok", "app": "Heimdall"}
