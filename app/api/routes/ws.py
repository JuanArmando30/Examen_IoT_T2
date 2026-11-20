"""Canal en tiempo real por unidad (Etapa 8).

- POST /ws/ticket (aparece en Swagger): ticket de un solo uso para el navegador.
- WS /ws/vehiculos/{id}?ticket=… (no aparece en Swagger; ver README).
  El ESP32 se conecta con la cabecera X-Dispositivo (su credencial).
"""

import asyncio
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Request, WebSocket

from app.api.dependencies import ClaveDep, ContenedorDep, PrincipalOpcional, esquema_invitado
from app.api.documentacion import SESION, TAG_TIEMPO_REAL
from app.core.exceptions import ErrorAplicacion
from app.core.limite import ip_cliente
from app.models.schemas import TicketOut, TicketSolicitud
from app.websocket import eventos

logger = logging.getLogger(__name__)

router = APIRouter()

CODIGO_CIERRE_NO_ENCONTRADO = 4404
CODIGO_CIERRE_NO_AUTORIZADO = 4401
CODIGO_CIERRE_PROHIBIDO = 4403
CODIGO_CIERRE_ERROR = 1011


@router.post("/ws/ticket", tags=[TAG_TIEMPO_REAL], summary="Ticket para suscribirse al WebSocket de una unidad",
             response_model=TicketOut, responses=SESION)
def pedir_ticket(cuerpo: TicketSolicitud, request: Request, contenedor: ContenedorDep,
                 principal: PrincipalOpcional, clave: ClaveDep,
                 token_invitado: Annotated[Optional[str], Depends(esquema_invitado)] = None):
    """Un solo uso y 30 s de vigencia. Se concede con las mismas reglas que REST:
    dueño de la unidad; administrador (inventario/exhibición, o vendida con soporte);
    invitado solo para su unidad reservada; clave X-API-Key (transición).
    Úsalo en `wss://…/ws/vehiculos/{id}?ticket=…`."""
    return contenedor.canal.emitir_ticket(cuerpo.id_vehiculo, ip_cliente(request), principal, token_invitado, clave)


@router.websocket("/ws/vehiculos/{id_vehiculo}")
async def monitorear_vehiculo(websocket: WebSocket, id_vehiculo: int, ticket: Optional[str] = None):
    """Eventos de UNA unidad. Al conectar envía el último estado; luego solo los
    eventos de esa unidad. "ping" → evento pong. El dispositivo (X-Dispositivo)
    además puede enviar reportes de ejecución."""

    contenedor = websocket.app.state.contenedor
    gestor = contenedor.gestor_ws

    await websocket.accept()

    try:
        if id_vehiculo <= 0:
            raise ErrorAplicacion("Identificador de vehículo inválido.")
        await asyncio.to_thread(contenedor.vehiculos.obtener_o_fallar, id_vehiculo)
        sujeto = await asyncio.to_thread(contenedor.canal.autorizar, id_vehiculo, ticket,
                                         websocket.headers.get("x-dispositivo"))
        estado = await asyncio.to_thread(contenedor.estados.obtener_o_none, id_vehiculo)
    except ErrorAplicacion as error:
        await _rechazar(websocket, id_vehiculo, error)
        return
    except Exception:
        logger.exception("Error al abrir el WebSocket del vehículo %s.", id_vehiculo)
        await _rechazar(websocket, id_vehiculo, ErrorAplicacion())
        return

    es_dispositivo = sujeto.tipo == "dispositivo"
    if es_dispositivo:
        # La presencia se publica ANTES de registrarlo: los navegadores reciben
        # «conectado» y el ESP32 recibe primero su estado_inicial (lo que espera el firmware).
        await contenedor.canal.dispositivo_conectado(id_vehiculo)
        estado = await asyncio.to_thread(contenedor.estados.obtener_o_none, id_vehiculo)
    cliente = gestor.registrar(id_vehiculo, websocket, sujeto)

    try:
        await gestor.enviar(cliente, eventos.estado_inicial(id_vehiculo, estado))

        while True:
            mensaje = await websocket.receive()

            if mensaje["type"] == "websocket.disconnect":
                break

            texto = (mensaje.get("text") or "").strip()

            if texto.lower() == "ping":
                await gestor.enviar(cliente, eventos.pong(id_vehiculo))
            elif es_dispositivo and texto:
                await contenedor.canal.mensaje_dispositivo(id_vehiculo, texto)

    except Exception as error:
        # Desconexiones abruptas o errores de envío: solo afectan a ESTE
        # cliente; los demás siguen conectados.
        logger.info("Cliente WebSocket del vehículo %s finalizó (%s).",
                    id_vehiculo, error.__class__.__name__)
    finally:
        gestor.desconectar(id_vehiculo, cliente)
        if es_dispositivo:
            await contenedor.canal.dispositivo_desconectado(id_vehiculo)


async def _rechazar(websocket, id_vehiculo, error):
    codigo = {404: CODIGO_CIERRE_NO_ENCONTRADO, 401: CODIGO_CIERRE_NO_AUTORIZADO,
              403: CODIGO_CIERRE_PROHIBIDO}.get(error.codigo_http, CODIGO_CIERRE_ERROR)
    nombre = {401: "WS_NO_AUTORIZADO", 403: "WS_PROHIBIDO"}.get(error.codigo_http, "WS_RECHAZADO")

    try:
        await websocket.send_json(eventos.error(id_vehiculo, nombre, error.mensaje))
        await websocket.close(code=codigo)
    except Exception:
        pass
