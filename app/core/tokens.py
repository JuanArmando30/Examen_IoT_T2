"""Tokens de sesión (Etapa 4).

- Token de ACCESO: JWT HS256 de vida corta (TOKEN_ACCESO_MIN). El frontend
  lo guarda solo en memoria y lo manda en «Authorization: Bearer …».
- Token de RENOVACIÓN: valor aleatorio opaco de 256 bits. En la base solo se
  guarda su HMAC-SHA256 (con TOKEN_SECRETO): una copia de la base no permite
  usarlo. Rota en cada uso.
- Códigos de restablecimiento: 10 caracteres legibles, guardados como HMAC.
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.core.exceptions import NoAutorizado

EMISOR = "vehiculos-iot"
ALGORITMO = "HS256"
_ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"     # sin 0/O ni 1/I/L


def ahora():
    return datetime.now(timezone.utc)


def emitir_acceso(auth, usuario):
    """Devuelve (token, expira_en UTC)."""
    expira = ahora() + timedelta(minutes=auth.acceso_min)
    datos = {
        "iss": EMISOR,
        "sub": str(usuario["id_usuario"]),
        "rol": usuario["rol"],
        "nombre": usuario["nombre"],
        "correo": usuario["correo"],
        "iat": int(ahora().timestamp()),
        "exp": int(expira.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(datos, auth.secreto, algorithm=ALGORITMO), expira


def verificar_acceso(auth, token):
    """Valida firma, emisor y vencimiento. Error → 401 (nunca se explica el motivo exacto)."""
    try:
        datos = jwt.decode(token, auth.secreto, algorithms=[ALGORITMO], issuer=EMISOR,
                           options={"require": ["exp", "sub", "rol", "iss"]})
    except jwt.ExpiredSignatureError as error:
        raise NoAutorizado("La sesión expiró: renuévala o inicia sesión de nuevo.") from error
    except jwt.PyJWTError as error:
        raise NoAutorizado("Token de acceso inválido.") from error
    if datos.get("rol") not in ("admin", "usuario"):
        raise NoAutorizado("Token de acceso inválido.")
    return datos


def secreto_aleatorio():
    return secrets.token_urlsafe(32)


def familia_nueva():
    return secrets.token_hex(16)


def huella(auth, valor):
    """HMAC-SHA256 hexadecimal (64 caracteres) con TOKEN_SECRETO."""
    return hmac.new(auth.secreto.encode("utf-8"), valor.encode("utf-8"), hashlib.sha256).hexdigest()


def codigo_restablecimiento():
    """XXXXX-XXXXX legible (≈50 bits); con límite de intentos y caducidad corta."""
    crudo = "".join(secrets.choice(_ALFABETO_CODIGO) for _ in range(10))
    return f"{crudo[:5]}-{crudo[5:]}"


def normalizar_codigo(codigo):
    return "".join(c for c in (codigo or "").upper() if c.isalnum())
