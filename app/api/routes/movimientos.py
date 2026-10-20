import asyncio

from fastapi import APIRouter

from app.api.dependencies import ContenedorDep, IdVehiculo, Operador
from app.api.documentacion import ESCRITURA, TAG_MOVIMIENTOS
from app.core.exceptions import ConflictoNegocio
from app.models.schemas import MovimientoRegistradoOut, MovimientoSolicitud
from app.websocket import eventos

router = APIRouter(prefix="/vehiculos/{id_vehiculo}/movimientos",
                   tags=[TAG_MOVIMIENTOS])


@router.post(
    "",
    summary="Registrar un movimiento individual",
    status_code=201,
    response_model=MovimientoRegistradoOut,
    responses=ESCRITURA,
)
async def registrar_movimiento(
    id_vehiculo: IdVehiculo, cuerpo: MovimientoSolicitud,
    contenedor: ContenedorDep, _rol: Operador,
):
    """Flujo: validar -> `sp_actualizar_estado` + `sp_registrar_historial`
    en **una transacción** -> COMMIT en RDS -> notificación WebSocket.

    Rechaza (sin tocar estado ni historial ni emitir evento) si el vehículo
    no existe/está inactivo, si el comando no existe, está inactivo o es de
    otro vehículo, o si hay una DEMO en ejecución.

    Requiere cabecera `X-API-Key`. Ejecutar un movimiento NO crea comandos
    nuevos (para eso: `POST /vehiculos/{id}/comandos`).

    **Stored Procedures:** `sp_obtener_vehiculo`,
    `sp_obtener_comandos_vehiculo`, `sp_obtener_estado`,
    `sp_actualizar_estado`, `sp_registrar_historial`.
    """
    if contenedor.demo_ejecutor.esta_ejecutando(id_vehiculo):
        raise ConflictoNegocio(
            "El vehículo está ejecutando una DEMO. Cancélala antes de "
            "enviar movimientos individuales."
        )

    # Bloqueante (MySQL) -> hilo. Al volver, la transacción ya se confirmó.
    resultado = await asyncio.to_thread(
        contenedor.movimientos.registrar,
        id_vehiculo, cuerpo.id_comando, cuerpo.codigo, cuerpo.origen,
    )

    notificados = await contenedor.gestor_ws.difundir(
        id_vehiculo, eventos.movimiento_individual(resultado)
    )
    resultado["clientes_notificados"] = notificados
    return resultado
