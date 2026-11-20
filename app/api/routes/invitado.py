"""Rutas públicas del INVITADO (Etapa 7): catálogo y reserva temporal.

Sin cuenta: la reserva entrega un token que el navegador guarda SOLO en
memoria y manda en la cabecera X-Invitado. Con ese token se usan las rutas
de siempre para mover y DEMO (POST /vehiculos/{id}/movimientos, …/iniciar,
…/demos/cancelar), únicamente sobre la unidad reservada.
"""

from typing import List

from fastapi import APIRouter, Request, Response

from app.api.dependencies import ContenedorDep, TokenInvitado
from app.api.documentacion import SESION, TAG_INVITADO
from app.core.limite import ip_cliente
from app.models.schemas import LatidoOut, ReservaCreadaOut, ReservaOut, ReservaSolicitud, UnidadCatalogoOut

router = APIRouter(prefix="/invitado", tags=[TAG_INVITADO])


@router.get("/catalogo", summary="Catálogo público de unidades en exhibición",
            response_model=List[UnidadCatalogoOut], responses=SESION)
def catalogo(contenedor: ContenedorDep):
    """Unidades en exhibición, su modelo y si se pueden reservar ahora.
    **SP:** `sp_catalogo_exhibicion`."""
    return contenedor.invitados.catalogo()


@router.post("/reservar", summary="Reservar la unidad de exhibición (5 min)", status_code=201,
             response_model=ReservaCreadaOut, responses=SESION)
async def reservar(cuerpo: ReservaSolicitud, request: Request, response: Response, contenedor: ContenedorDep):
    """Reserva EXCLUSIVA y temporal. 409 si la exhibición está cerrada o la unidad
    está ocupada (con el tiempo que falta); 429 si la misma red reservó hace poco.
    **SP:** `sp_invitado_reservar`, `sp_comandos_invitado`."""
    response.headers["Cache-Control"] = "no-store"
    return await contenedor.invitados.reservar(cuerpo.id_vehiculo, ip_cliente(request))


@router.get("/estado", summary="Mi reserva", response_model=ReservaOut, responses=SESION)
def estado(token: TokenInvitado, contenedor: ContenedorDep):
    """Tiempo restante, comandos y DEMO disponibles para el invitado."""
    return contenedor.invitados.estado(token)


@router.post("/latido", summary="Sigo aquí", response_model=LatidoOut, responses=SESION)
def latido(token: TokenInvitado, contenedor: ContenedorDep):
    """El navegador lo envía cada pocos segundos. Si deja de llegar (pestaña
    cerrada, sin red) la API detiene la unidad y libera la reserva."""
    return contenedor.invitados.latido(token)


@router.post("/terminar", summary="Terminar mi reserva", status_code=204, responses=SESION)
async def terminar(token: TokenInvitado, contenedor: ContenedorDep):
    """Cancela la DEMO si corre, envía DETENER y libera la unidad."""
    await contenedor.invitados.terminar(token)
    return Response(status_code=204)
