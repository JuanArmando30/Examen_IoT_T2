"""Dependencias compartidas por los endpoints."""

from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Path, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.contenedor import Contenedor
from app.core.exceptions import NoAutorizado, Prohibido
from app.core.security import ROL_ADMIN, ROL_OPERADOR, identificar_rol
from app.services.administracion import Actor
from app.services.auth_service import Principal

esquema_api_key = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description=(
        "Clave de API. Operador: escrituras y control (movimientos, DEMO). "
        "Administrador: además eliminar registros."
    ),
)


esquema_invitado = APIKeyHeader(
    name="X-Invitado",
    auto_error=False,
    description="Token de la reserva de invitado (POST /invitado/reservar). Solo sirve para la unidad reservada.",
)

esquema_bearer = HTTPBearer(
    auto_error=False,
    description="Token de acceso de POST /auth/login (vigencia corta; se renueva con /auth/renovar).",
)


def obtener_contenedor(request: Request) -> Contenedor:
    return request.app.state.contenedor


ContenedorDep = Annotated[Contenedor, Depends(obtener_contenedor)]
ClaveDep = Annotated[Optional[str], Depends(esquema_api_key)]


def principal_opcional(
    contenedor: ContenedorDep,
    credenciales: Annotated[Optional[HTTPAuthorizationCredentials], Depends(esquema_bearer)],
) -> Optional[Principal]:
    """Usuario del token Bearer; None si no se envió. Token inválido → 401."""
    if credenciales is None:
        return None
    return contenedor.auth.principal_desde_token(credenciales.credentials)


PrincipalOpcional = Annotated[Optional[Principal], Depends(principal_opcional)]


def requiere_sesion(principal: PrincipalOpcional) -> Principal:
    if principal is None:
        raise NoAutorizado()
    return principal


Sesion = Annotated[Principal, Depends(requiere_sesion)]


def obtener_rol(
    contenedor: ContenedorDep,
    clave: Annotated[Optional[str], Depends(esquema_api_key)],
    principal: PrincipalOpcional,
) -> Optional[str]:
    """Rol para las escrituras del catálogo técnico (vehículos, comandos, DEMO).

    - Clave X-API-Key (transición): manda la clave, como siempre.
    - Sin clave: el token de un administrador equivale a la clave de admin
      (Etapa 5: el administrador con sesión no necesita escribir la clave).
      Un token de comprador no basta → 403.
    """
    if clave:
        return identificar_rol(clave, contenedor.seguridad)
    if principal is not None:
        if not principal.es_admin:
            raise Prohibido("Esta operación es solo para administradores.")
        return ROL_ADMIN
    return None


RolDep = Annotated[Optional[str], Depends(obtener_rol)]


def requiere_operador(rol: RolDep) -> str:
    """401 si falta/errónea la clave. Acepta operador y administrador."""

    if rol is None:
        raise HTTPException(
            status_code=401,
            detail="Inicia sesión (token de acceso) para esta operación.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return rol


def requiere_admin(rol: RolDep) -> str:
    """401 sin clave válida; 403 si la clave no es de administrador."""

    rol = requiere_operador(rol)

    if rol != ROL_ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Esta operación es solo para administradores.",
        )

    return rol


def requiere_control(
    contenedor: ContenedorDep,
    clave: Annotated[Optional[str], Depends(esquema_api_key)],
) -> str:
    """Operaciones de CONTROL (mover, DEMO, /sesion).

    - Con clave: debe ser válida (401 si no lo es), igual que siempre.
    - Sin clave: se acepta como operador SOLO si CONTROL_ABIERTO=true.
    Crear, editar y eliminar NO usan esta dependencia.
    """

    if clave:
        return requiere_operador(identificar_rol(clave, contenedor.seguridad))

    if contenedor.seguridad.control_abierto:
        return ROL_OPERADOR

    return requiere_operador(None)


Operador = Annotated[str, Depends(requiere_operador)]
Control = Annotated[str, Depends(requiere_control)]
Administrador = Annotated[str, Depends(requiere_admin)]


def actor_administrador(
    contenedor: ContenedorDep, clave: ClaveDep, principal: PrincipalOpcional,
) -> Actor:
    """Quién hace una operación de ADMINISTRACIÓN.

    - Token de un usuario con rol admin → su id queda en la auditoría.
    - Token de otro rol → 403.
    - Transición (hasta la Etapa 9): clave X-API-Key de administrador
      (id_usuario = None).
    """
    if principal is not None:
        if not principal.es_admin:
            raise Prohibido("Esta operación es solo para administradores.")
        return principal.actor()
    requiere_admin(identificar_rol(clave, contenedor.seguridad))
    return Actor(id_usuario=None, rol=ROL_ADMIN, via="clave")


def autorizar_control_unidad(
    id_vehiculo: Annotated[int, Path(gt=0)],
    contenedor: ContenedorDep, clave: ClaveDep, principal: PrincipalOpcional,
    token_invitado: Annotated[Optional[str], Depends(esquema_invitado)] = None,
) -> Actor:
    """CONTROL de UNA unidad (mover, iniciar/cancelar DEMO).

    - Invitado (X-Invitado): solo la unidad de SU reserva vigente.
    - Con token: autorización por unidad (dueño; admin según estado/soporte).
    - Transición: clave X-API-Key válida, o sin nada si CONTROL_ABIERTO=true.
    La exclusividad de una reserva de invitado se aplica en cada ruta
    (contenedor.invitados.exigir_control) porque DETENER siempre debe pasar.
    """
    if token_invitado:
        return contenedor.invitados.actor(token_invitado, id_vehiculo)
    if principal is not None:
        contenedor.auth.exigir_acceso_unidad(principal, id_vehiculo)
        return principal.actor()
    if clave:
        rol = requiere_operador(identificar_rol(clave, contenedor.seguridad))
        return Actor(id_usuario=None, rol=rol, via="clave")
    if contenedor.seguridad.control_abierto:
        return Actor(id_usuario=None, rol=ROL_OPERADOR, via="abierto")
    raise NoAutorizado("Inicia sesión para controlar la unidad (o reserva la de exhibición como invitado).")


def autorizar_lectura_unidad(
    id_vehiculo: Annotated[int, Path(gt=0)],
    contenedor: ContenedorDep, clave: ClaveDep, principal: PrincipalOpcional,
) -> None:
    """Lectura de UNA unidad (estado, historial, comandos, DEMO).

    Con LECTURA_ABIERTA=true (transición) cualquiera puede leer, como antes.
    Con false: mismas reglas que el control, o una clave X-API-Key válida.
    """
    if contenedor.config_auth.lectura_abierta:          # con token no se lee MENOS que sin él
        return
    if principal is not None:
        contenedor.auth.exigir_acceso_unidad(principal, id_vehiculo)
        return
    if clave:
        requiere_operador(identificar_rol(clave, contenedor.seguridad))
        return
    raise NoAutorizado()


ActorAdmin = Annotated[Actor, Depends(actor_administrador)]
ControlUnidad = Annotated[Actor, Depends(autorizar_control_unidad)]
LecturaUnidad = Annotated[None, Depends(autorizar_lectura_unidad)]
IdModelo = Annotated[
    int, Path(gt=0, description="Identificador del modelo", examples=[1])
]
IdUsuario = Annotated[
    int, Path(gt=0, description="Identificador del usuario", examples=[1])
]
IdAsignacion = Annotated[
    int, Path(gt=0, description="Identificador de la asignación", examples=[1])
]

IdVehiculo = Annotated[
    int, Path(gt=0, description="Identificador del vehículo", examples=[1])
]
IdComando = Annotated[
    int, Path(gt=0, description="Identificador del comando", examples=[1])
]
IdDemo = Annotated[
    int, Path(gt=0, description="Identificador de la DEMO", examples=[1])
]
IdMovimiento = Annotated[
    int,
    Path(gt=0, description="Identificador del movimiento de la DEMO",
         examples=[1]),
]


def token_invitado(
    token: Annotated[Optional[str], Depends(esquema_invitado)],
) -> str:
    if not token:
        raise NoAutorizado("Falta la cabecera X-Invitado de tu reserva.")
    return token


TokenInvitado = Annotated[str, Depends(token_invitado)]
