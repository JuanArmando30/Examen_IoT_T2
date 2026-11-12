"""Panel web de control (pagina estatica) y verificacion de la clave de API."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.dependencies import Control, ContenedorDep
from app.api.documentacion import R401, TAG_SISTEMA

router = APIRouter()

# app/api/routes/control.py -> app/static/control.html
RUTA_PANEL = Path(__file__).resolve().parents[2] / "static" / "control.html"

CABECERAS = {
    "Cache-Control": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


class SesionOut(BaseModel):
    rol: str
    # "clave": se validó una X-API-Key · "abierto": sin clave, con CONTROL_ABIERTO=true
    acceso: str = "clave"


@router.get("/control", include_in_schema=False)
def panel_de_control():
    """Pagina del control remoto (HTML estatico). No contiene claves."""
    return FileResponse(
        RUTA_PANEL, media_type="text/html; charset=utf-8", headers=CABECERAS
    )


@router.get(
    "/sesion",
    tags=[TAG_SISTEMA],
    summary="Verificar la clave X-API-Key",
    response_model=SesionOut,
    responses=R401,
)
def verificar_sesion(rol: Control, contenedor: ContenedorDep, request: Request):
    """Comprueba la clave **sin modificar datos**.

    Devuelve el rol (`operador` o `admin`) y cómo se obtuvo el acceso.
    Responde 401 si la cabecera `X-API-Key` es incorrecta, o si falta y
    `CONTROL_ABIERTO` no está activo. Sin clave y con `CONTROL_ABIERTO=true`
    responde `{"rol": "operador", "acceso": "abierto"}`.
    """
    abierto = not request.headers.get("X-API-Key") and contenedor.seguridad.control_abierto
    return {"rol": rol, "acceso": "abierto" if abierto else "clave"}
