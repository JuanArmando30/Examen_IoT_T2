"""Sesión (/auth) y unidades del comprador (/mis-vehiculos) — Etapa 4.

Todas son funciones `def` (no async): Argon2 y MySQL bloquean, así que
FastAPI las ejecuta en su grupo de hilos sin frenar el WebSocket.
Las respuestas con tokens llevan `Cache-Control: no-store`.
"""

from typing import List

from fastapi import APIRouter, Request, Response

from app.api.dependencies import ContenedorDep, IdVehiculo, Sesion
from app.api.documentacion import SESION, SESION_PRIVADA, TAG_MIS, TAG_SESION
from app.core.limite import ip_cliente
from app.models.schemas import (
    CambiarContrasenaSolicitud, LoginSolicitud, MensajeOut, MiVehiculoOut, RenovarSolicitud,
    RestablecerSolicitud, SesionOut, SoporteOtorgar, SoporteOut, SoporteRevocadoOut,
    UsuarioSesionOut,
)

router = APIRouter()


def _sin_cache(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _agente(request: Request):
    return request.headers.get("user-agent", "")


# ============================ /auth ============================


@router.post("/auth/login", tags=[TAG_SESION], summary="Iniciar sesión",
             response_model=SesionOut, responses=SESION)
def login(cuerpo: LoginSolicitud, request: Request, response: Response,
          contenedor: ContenedorDep):
    """Correo + contraseña → token de acceso (Bearer, corto) y token de renovación.

    - Error genérico (401) sin revelar si el correo existe.
    - 5 fallos seguidos bloquean la cuenta 15 min (429); además hay límite por IP.

    **SP:** `sp_login_obtener`, `sp_login_resultado`, `sp_token_crear`.
    """
    _sin_cache(response)
    return contenedor.auth.login(cuerpo.correo, cuerpo.contrasena, ip_cliente(request),
                                 _agente(request))


@router.post("/auth/renovar", tags=[TAG_SESION], summary="Renovar la sesión",
             response_model=SesionOut, responses=SESION)
def renovar(cuerpo: RenovarSolicitud, request: Request, response: Response,
            contenedor: ContenedorDep):
    """Cambia el token de renovación por uno NUEVO (rotación) y emite otro de acceso.

    Si se presenta un token de renovación ya usado se cierra toda esa sesión
    (posible robo) y se responde 401.

    **SP:** `sp_token_usar`.
    """
    _sin_cache(response)
    return contenedor.auth.renovar(cuerpo.token_renovacion, ip_cliente(request),
                                   _agente(request))


@router.post("/auth/salir", tags=[TAG_SESION], summary="Cerrar sesión",
             status_code=204, responses=SESION)
def salir(cuerpo: RenovarSolicitud, contenedor: ContenedorDep):
    """Revoca el token de renovación (y su familia). El token de acceso vence solo
    en minutos; el frontend debe borrarlo de memoria.

    **SP:** `sp_token_revocar`.
    """
    contenedor.auth.salir(cuerpo.token_renovacion)
    return Response(status_code=204)


@router.get("/auth/yo", tags=[TAG_SESION], summary="Usuario de la sesión",
            response_model=UsuarioSesionOut, responses=SESION)
def yo(principal: Sesion, response: Response):
    """Datos del usuario del token (releídos de la base). **SP:** `sp_obtener_usuario_auth`."""
    _sin_cache(response)
    return {
        "id_usuario": principal.id_usuario, "correo": principal.correo,
        "nombre": principal.nombre, "rol": principal.rol,
        "debe_cambiar_contrasena": principal.debe_cambiar_contrasena,
    }


@router.post("/auth/restablecer", tags=[TAG_SESION],
             summary="Restablecer la contraseña con un código del administrador",
             response_model=MensajeOut, responses=SESION)
def restablecer(cuerpo: RestablecerSolicitud, request: Request, contenedor: ContenedorDep):
    """El código es de un solo uso, caduca en 30 min y se bloquea tras 5 intentos.
    Al usarlo se cierran todas las sesiones de esa cuenta.

    **SP:** `sp_codigo_usar`.
    """
    return contenedor.auth.restablecer(cuerpo.correo, cuerpo.codigo, cuerpo.contrasena_nueva,
                                       ip_cliente(request))


@router.post("/auth/cambiar-contrasena", tags=[TAG_SESION], summary="Cambiar mi contraseña",
             response_model=SesionOut, responses=SESION)
def cambiar_contrasena(cuerpo: CambiarContrasenaSolicitud, principal: Sesion,
                       request: Request, response: Response, contenedor: ContenedorDep):
    """Exige la contraseña actual. Cierra las demás sesiones y devuelve una sesión nueva.

    **SP:** `sp_login_obtener`, `sp_cambiar_contrasena`, `sp_token_crear`.
    """
    _sin_cache(response)
    return contenedor.auth.cambiar_contrasena(principal, cuerpo.contrasena_actual,
                                              cuerpo.contrasena_nueva, _agente(request))


# ======================= /mis-vehiculos =======================


@router.get("/mis-vehiculos", tags=[TAG_MIS], summary="Mis unidades",
            response_model=List[MiVehiculoOut], responses=SESION_PRIVADA)
def mis_vehiculos(principal: Sesion, contenedor: ContenedorDep):
    """Solo las unidades con asignación vigente a la cuenta del token.
    **SP:** `sp_mis_vehiculos`."""
    return contenedor.auth.mis_vehiculos(principal)


@router.get("/mis-vehiculos/{id_vehiculo}/soporte", tags=[TAG_MIS],
            summary="Autorizaciones de soporte de mi unidad",
            response_model=List[SoporteOut], responses=SESION_PRIVADA)
def listar_soporte(id_vehiculo: IdVehiculo, principal: Sesion, contenedor: ContenedorDep):
    """Dueño de la unidad (o administrador). **SP:** `sp_acceso_unidad`, `sp_soporte_listar`."""
    return contenedor.auth.soporte_listar(principal, id_vehiculo)


@router.post("/mis-vehiculos/{id_vehiculo}/soporte", tags=[TAG_MIS], status_code=201,
             summary="Autorizar soporte temporal",
             response_model=SoporteOut, responses=SESION_PRIVADA)
def otorgar_soporte(id_vehiculo: IdVehiculo, cuerpo: SoporteOtorgar, principal: Sesion,
                    contenedor: ContenedorDep):
    """El comprador permite que la empresa opere SU unidad durante 1–72 h
    (a un administrador concreto o a cualquiera). Queda en la auditoría.

    **SP:** `sp_acceso_unidad`, `sp_soporte_otorgar`, `sp_soporte_listar`.
    """
    return contenedor.auth.soporte_otorgar(principal, id_vehiculo, cuerpo.horas, cuerpo.motivo,
                                           cuerpo.id_administrador)


@router.post("/mis-vehiculos/{id_vehiculo}/soporte/revocar", tags=[TAG_MIS],
             summary="Revocar el soporte",
             response_model=SoporteRevocadoOut, responses=SESION_PRIVADA)
def revocar_soporte(id_vehiculo: IdVehiculo, principal: Sesion, contenedor: ContenedorDep):
    """Termina de inmediato las autorizaciones vigentes que dio el comprador.
    **SP:** `sp_acceso_unidad`, `sp_soporte_revocar`."""
    return contenedor.auth.soporte_revocar(principal, id_vehiculo)
