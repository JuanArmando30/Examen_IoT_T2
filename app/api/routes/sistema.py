from fastapi import APIRouter

from app.api.dependencies import ContenedorDep
from app.api.documentacion import BASE, TAG_SISTEMA
from app.models.schemas import SaludOut

router = APIRouter(tags=[TAG_SISTEMA])


@router.get("/", summary="Estado del servicio", response_model=SaludOut)
def inicio():
    """Comprueba que la API responde en http://localhost:8000."""
    return {"estado": "ok"}


@router.get("/health", summary="Salud de la API", response_model=SaludOut)
def salud():
    """Liveness: el proceso FastAPI está vivo (no consulta RDS)."""
    return {"estado": "ok"}


@router.get(
    "/health/db",
    summary="Salud de la conexión a Amazon RDS",
    response_model=SaludOut,
    responses=BASE,
)
def salud_base_datos(contenedor: ContenedorDep):
    """Ejecuta una consulta fija (SELECT 1). Devuelve 503 si RDS no responde."""
    contenedor.verificar_base_datos()
    return {"estado": "ok"}
