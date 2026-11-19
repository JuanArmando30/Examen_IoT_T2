"""Contraseñas con Argon2id (argon2-cffi, parámetros recomendados por defecto)."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.exceptions import SolicitudInvalida

_hasher = PasswordHasher()
# Hash de una contraseña que nadie conoce: se verifica cuando el correo no
# existe para que la respuesta tarde lo mismo (no revela qué correos existen).
_HASH_FICTICIO = _hasher.hash("contraseña-ficticia-para-igualar-tiempos")

MIN_LONGITUD = 10
MAX_LONGITUD = 128


def hashear(contrasena):
    return _hasher.hash(contrasena)


def verificar(hash_guardado, contrasena):
    try:
        return _hasher.verify(hash_guardado or _HASH_FICTICIO, contrasena) and bool(hash_guardado)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def igualar_tiempo(contrasena):
    verificar(None, contrasena)


def validar_politica(contrasena, correo=""):
    if not MIN_LONGITUD <= len(contrasena or "") <= MAX_LONGITUD:
        raise SolicitudInvalida(f"La contraseña debe tener entre {MIN_LONGITUD} y {MAX_LONGITUD} caracteres.")
    if not any(c.isalpha() for c in contrasena) or not any(c.isdigit() for c in contrasena):
        raise SolicitudInvalida("La contraseña debe incluir letras y números.")
    usuario = (correo or "").split("@")[0].lower()
    if usuario and len(usuario) >= 4 and usuario in contrasena.lower():
        raise SolicitudInvalida("La contraseña no debe contener tu correo.")
