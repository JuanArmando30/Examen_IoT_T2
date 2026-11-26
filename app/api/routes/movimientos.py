import asyncio

from fastapi import APIRouter

from app.api.dependencies import ContenedorDep, ControlUnidad, IdVehiculo
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
    contenedor: ContenedorDep, actor: ControlUnidad,
):
    """Flujo: validar -> `sp_actualizar_estado` + `sp_registrar_historial`
    en **una transacción** -> COMMIT en RDS -> notificación WebSocket.

    Rechaza (sin tocar estado ni historial ni emitir evento) si el vehículo
    no existe/está inactivo, si el comando no existe, está inactivo o es de
    otro vehículo, o si hay una DEMO en ejecución. **DETENER tiene prioridad**:
    durante una DEMO la cancela y se registra.

    Autorización: token del **dueño** de la unidad, o de un administrador
    (inventario/exhibición, o vendida con soporte vigente). Transición:
    cabecera `X-API-Key`, o nada con `CONTROL_ABIERTO=true`. Ejecutar un movimiento NO crea comandos
    nuevos (para eso: `POST /vehiculos/{id}/comandos`).

    **Stored Procedures:** `sp_obtener_vehiculo`,
    `sp_obtener_comandos_vehiculo`, `sp_obtener_estado`,
    `sp_actualizar_estado`, `sp_registrar_historial`.
    """
    detener = await asyncio.to_thread(contenedor.comandos.buscar_detener, id_vehiculo)
    es_detener = detener is not None and (
        cuerpo.id_comando == detener["id_comando"] or cuerpo.codigo == detener["codigo"])

    # Reserva de invitado (Etapa 7): exclusiva salvo DETENER; el invitado solo
    # usa los comandos que su modelo le permite.
    contenedor.invitados.exigir_control(id_vehiculo, actor, es_detener)
    if actor.rol == "invitado":
        contenedor.invitados.exigir_comando(id_vehiculo, cuerpo.id_comando, cuerpo.codigo)

    if contenedor.demo_ejecutor.esta_ejecutando(id_vehiculo):
        # DETENER tiene prioridad: cancela la DEMO y se registra. Cualquier
        # otro movimiento se rechaza mientras corre la DEMO.
        if not es_detener:
            raise ConflictoNegocio(
                "El vehículo está ejecutando una DEMO. Cancélala (o envía DETENER) "
                "antes de enviar movimientos individuales."
            )
        try:
            await contenedor.demo_ejecutor.cancelar(id_vehiculo)
        except ConflictoNegocio:
            pass                                   # terminó justo ahora: nada que cancelar

    # Bloqueante (MySQL) -> hilo. Al volver, la transacción ya se confirmó.
    resultado = await asyncio.to_thread(
        contenedor.movimientos.registrar,
        id_vehiculo, cuerpo.id_comando, cuerpo.codigo, cuerpo.origen, actor,
    )

    notificados = await contenedor.gestor_ws.difundir(
        id_vehiculo, eventos.movimiento_individual(resultado)
    )
    resultado["clientes_notificados"] = notificados
    # Invitado: cada orden queda también en la bitácora (qué hizo durante su reserva).
    await contenedor.invitados.auditar_accion(actor, id_vehiculo, "invitado.movimiento", {
        "comando": resultado["comando"], "codigo": resultado["codigo"], "origen": resultado["origen"]})
    return resultado
