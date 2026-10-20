import asyncio

from fastapi import APIRouter

from app.api.dependencies import ContenedorDep, IdVehiculo, Operador
from app.api.documentacion import ESCRITURA, LECTURA, TAG_ESTADO
from app.models.schemas import EstadoActualizar, EstadoOut
from app.websocket import eventos

router = APIRouter(prefix="/vehiculos/{id_vehiculo}/estado",
                   tags=[TAG_ESTADO])


@router.get(
    "",
    summary="Último estado registrado",
    response_model=EstadoOut,
    responses=LECTURA,
)
def obtener_estado(id_vehiculo: IdVehiculo, contenedor: ContenedorDep):
    """**Stored Procedures:** `sp_obtener_vehiculo` y `sp_obtener_estado`.

    404 si el vehículo no existe o todavía no tiene estado.
    """
    return contenedor.estados.obtener(id_vehiculo)


@router.post(
    "",
    summary="Actualizar el indicador de conexión",
    response_model=EstadoOut,
    responses=ESCRITURA,
)
async def actualizar_estado(
    id_vehiculo: IdVehiculo, cuerpo: EstadoActualizar,
    contenedor: ContenedorDep, _rol: Operador,
):
    """Cambia `conectado` (y opcionalmente el último comando) SIN escribir
    en el historial. Notifica el cambio a los clientes WebSocket.

    **Stored Procedures:** `sp_actualizar_estado` y `sp_obtener_estado`.
    """
    estado = await asyncio.to_thread(
        contenedor.estados.actualizar,
        id_vehiculo, cuerpo.conectado, cuerpo.id_comando,
    )
    await contenedor.gestor_ws.difundir(
        id_vehiculo, eventos.estado_actualizado(id_vehiculo, estado)
    )
    return estado
