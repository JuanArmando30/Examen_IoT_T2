"""Dependencias compartidas por los endpoints."""

from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Path, Request
from fastapi.security import APIKeyHeader

from app.contenedor import Contenedor
from app.core.security import ROL_ADMIN, identificar_rol

esquema_api_key = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description=(
        "Clave de API. Operador: escrituras y control (movimientos, DEMO). "
        "Administrador: además eliminar registros."
    ),
)


def obtener_contenedor(request: Request) -> Contenedor:
    return request.app.state.contenedor


ContenedorDep = Annotated[Contenedor, Depends(obtener_contenedor)]


def obtener_rol(
    contenedor: ContenedorDep,
    clave: Annotated[Optional[str], Depends(esquema_api_key)],
) -> Optional[str]:
    return identificar_rol(clave, contenedor.seguridad)


RolDep = Annotated[Optional[str], Depends(obtener_rol)]


def requiere_operador(rol: RolDep) -> str:
    """401 si falta/errónea la clave. Acepta operador y administrador."""

    if rol is None:
        raise HTTPException(
            status_code=401,
            detail="Falta la cabecera X-API-Key o la clave no es válida.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return rol


def requiere_admin(rol: RolDep) -> str:
    """401 sin clave válida; 403 si la clave no es de administrador."""

    rol = requiere_operador(rol)

    if rol != ROL_ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Esta operación requiere la clave de administrador.",
        )

    return rol


Operador = Annotated[str, Depends(requiere_operador)]
Administrador = Annotated[str, Depends(requiere_admin)]

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
