from fastapi import APIRouter

from app.api.dependencies import ContenedorDep, IdVehiculo
from app.api.documentacion import LECTURA, TAG_HISTORIAL
from app.models.schemas import HistorialOut
from app.services.historial_service import LIMITE_HISTORIAL

router = APIRouter(prefix="/vehiculos/{id_vehiculo}/historial",
                   tags=[TAG_HISTORIAL])


@router.get(
    "",
    summary="Últimos 10 movimientos individuales",
    response_model=HistorialOut,
    responses=LECTURA,
)
def obtener_historial(id_vehiculo: IdVehiculo, contenedor: ContenedorDep):
    """Devuelve **como máximo 10** movimientos individuales, del más
    reciente al más antiguo. Si hay menos, devuelve solo los disponibles
    (lista vacía si no hay ninguno). Los movimientos de DEMO nunca
    aparecen aquí. El historial completo se conserva en RDS.

    **Stored Procedures:** `sp_obtener_vehiculo` (existencia) y
    `sp_obtener_historial`.
    """
    registros = contenedor.historial.ultimos(id_vehiculo)
    return {
        "id_vehiculo": id_vehiculo,
        "limite": LIMITE_HISTORIAL,
        "total_devueltos": len(registros),
        "movimientos": registros,
    }
