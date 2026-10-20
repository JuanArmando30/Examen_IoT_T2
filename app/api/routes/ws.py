"""Endpoint WebSocket (no aparece en Swagger; ver README)."""

import asyncio
import logging

from fastapi import APIRouter, WebSocket

from app.core.exceptions import ErrorAplicacion
from app.websocket import eventos

logger = logging.getLogger(__name__)

router = APIRouter()

CODIGO_CIERRE_NO_ENCONTRADO = 4404
CODIGO_CIERRE_ERROR = 1011


@router.websocket("/ws/vehiculos/{id_vehiculo}")
async def monitorear_vehiculo(websocket: WebSocket, id_vehiculo: int):
    """Monitorea UN vehículo: ws://localhost:8000/ws/vehiculos/{id}.

    Al conectar envía el último estado. Después recibe solo los eventos de
    ese vehículo. El cliente puede enviar el texto "ping" y recibe "pong".
    """

    contenedor = websocket.app.state.contenedor
    gestor = contenedor.gestor_ws

    await websocket.accept()

    # Validar el vehículo y leer el último estado (bloqueante -> hilo).
    try:
        if id_vehiculo <= 0:
            raise ErrorAplicacion("Identificador de vehículo inválido.")

        await asyncio.to_thread(
            contenedor.vehiculos.obtener_o_fallar, id_vehiculo
        )
        estado = await asyncio.to_thread(
            contenedor.estados.obtener_o_none, id_vehiculo
        )
    except ErrorAplicacion as error:
        await _rechazar(websocket, id_vehiculo, error)
        return
    except Exception:
        logger.exception("Error al abrir el WebSocket del vehículo %s.",
                         id_vehiculo)
        await _rechazar(websocket, id_vehiculo, ErrorAplicacion())
        return

    cliente = gestor.registrar(id_vehiculo, websocket)

    try:
        await gestor.enviar(cliente, eventos.estado_inicial(id_vehiculo, estado))

        while True:
            mensaje = await websocket.receive()

            if mensaje["type"] == "websocket.disconnect":
                break

            texto = (mensaje.get("text") or "").strip().lower()

            if texto == "ping":
                await gestor.enviar(cliente, eventos.pong(id_vehiculo))

    except Exception as error:
        # Desconexiones abruptas o errores de envío: solo afectan a ESTE
        # cliente; los demás siguen conectados.
        logger.info("Cliente WebSocket del vehículo %s finalizó (%s).",
                    id_vehiculo, error.__class__.__name__)
    finally:
        gestor.desconectar(id_vehiculo, cliente)


async def _rechazar(websocket, id_vehiculo, error):
    codigo = (CODIGO_CIERRE_NO_ENCONTRADO if error.codigo_http == 404
              else CODIGO_CIERRE_ERROR)

    try:
        await websocket.send_json(eventos.error(
            id_vehiculo, "WS_RECHAZADO", error.mensaje,
        ))
        await websocket.close(code=codigo)
    except Exception:
        pass
