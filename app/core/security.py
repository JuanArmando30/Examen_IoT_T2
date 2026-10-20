"""Autenticación y autorización basadas en claves de API."""

import secrets
from typing import Optional

from app.core.config import SeguridadSettings

ROL_OPERADOR = "operador"
ROL_ADMIN = "admin"


def _coinciden(a: str, b: str) -> bool:
    # compare_digest evita ataques de temporización.
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def identificar_rol(
    clave: Optional[str],
    settings: SeguridadSettings,
) -> Optional[str]:
    """Devuelve el rol asociado a la clave o None si no es válida."""

    if not clave:
        return None

    if _coinciden(clave, settings.api_key_admin):
        return ROL_ADMIN

    if _coinciden(clave, settings.api_key_operador):
        return ROL_OPERADOR

    return None
