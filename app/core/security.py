"""Autenticación y autorización basadas en claves de API."""

import secrets
from typing import Optional

from app.core.config import SeguridadSettings
from app.core.exceptions import NoAutorizado

MENSAJE_CLAVE_RETIRADA = (
    "La clave X-API-Key se retiró: inicia sesión con tu cuenta (Administración) "
    "y usa el token de acceso."
)

ROL_OPERADOR = "operador"
ROL_ADMIN = "admin"


def _coinciden(a: str, b: str) -> bool:
    # compare_digest evita ataques de temporización.
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def identificar_rol(
    clave: Optional[str],
    settings: SeguridadSettings,
) -> Optional[str]:
    """Devuelve el rol asociado a la clave o None si no es válida.

    Con la clave retirada (CLAVE_API_HABILITADA=false), enviarla responde 401
    con un mensaje que indica qué hacer en su lugar.
    """

    if not clave:
        return None

    if not settings.clave_habilitada:
        raise NoAutorizado(MENSAJE_CLAVE_RETIRADA)

    if _coinciden(clave, settings.api_key_admin):
        return ROL_ADMIN

    if _coinciden(clave, settings.api_key_operador):
        return ROL_OPERADOR

    return None
