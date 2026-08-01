# Heimdall API — entrypoint FastAPI
import logging
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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


# Descarga de builds: /download/heimdall-v8.apk
# Sirve los APK desde /root/proyectos/heimdall-app/build/app/outputs/flutter-apk/
_BUILD_DIR = "/root/proyectos/heimdall-app/build/app/outputs/flutter-apk"


@app.get("/download/{filename}")
def download_build(filename: str):
    """Descarga directa de un build (APK). Sin auth: son builds públicos del proyecto."""
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Nombre inválido")
    path = os.path.join(_BUILD_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Build no encontrado")
    return FileResponse(path, media_type="application/vnd.android.package-archive",
                        filename=filename)
