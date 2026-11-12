import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


# Ruta de la carpeta raíz del proyecto
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Cargar las variables del archivo .env
load_dotenv(PROJECT_ROOT / ".env")

LONGITUD_MINIMA_CLAVE_API = 12
VERDADERO = {"1", "true", "si", "sí", "yes", "on"}

# Origen del frontend publicado en GitHub Pages (solo esquema + dominio, sin ruta).
ORIGEN_CORS_POR_DEFECTO = "https://juanarmando30.github.io"


def origenes_cors():
    """Orígenes autorizados para llamar a la API desde el navegador (CORS).

    Se leen de CORS_ORIGINS (separados por comas). CORS no autentica a nadie:
    solo indica al navegador qué páginas pueden leer las respuestas. La
    protección de escrituras sigue siendo la cabecera X-API-Key.
    """

    valor = os.getenv("CORS_ORIGINS", ORIGEN_CORS_POR_DEFECTO)
    origenes = [o.strip().rstrip("/") for o in valor.split(",") if o.strip()]

    for origen in origenes:
        if origen == "*" or not origen.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError(f"Origen CORS no permitido: {origen!r}")

    return origenes


@dataclass(frozen=True)
class Settings:
    """Configuración de la conexión a MySQL (Amazon RDS)."""

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    # repr=False evita que la contraseña aparezca en logs o en print().
    db_password: str = field(repr=False)

    @classmethod
    def from_env(cls):
        """Leer y validar la configuración de MySQL."""

        required_vars = {
            "DB_HOST": os.getenv("DB_HOST"),
            "DB_NAME": os.getenv("DB_NAME"),
            "DB_USER": os.getenv("DB_USER"),
            "DB_PASSWORD": os.getenv("DB_PASSWORD"),
        }

        missing = [
            name
            for name, value in required_vars.items()
            if not value
        ]

        if missing:
            raise ValueError(
                "Faltan variables en el archivo .env: "
                + ", ".join(missing)
            )

        try:
            db_port = int(os.getenv("DB_PORT", "3306"))
        except ValueError as error:
            raise ValueError(
                "DB_PORT debe ser un número entero."
            ) from error

        if not 1 <= db_port <= 65535:
            raise ValueError(
                "DB_PORT debe estar entre 1 y 65535."
            )

        return cls(
            db_host=required_vars["DB_HOST"],
            db_port=db_port,
            db_name=required_vars["DB_NAME"],
            db_user=required_vars["DB_USER"],
            db_password=required_vars["DB_PASSWORD"],
        )


@dataclass(frozen=True)
class SeguridadSettings:
    """Claves de acceso a la API (autenticación por cabecera X-API-Key).

    - API_KEY_OPERADOR: permite operaciones de escritura y control.
    - API_KEY_ADMIN: además permite operaciones destructivas (eliminar).
    - CONTROL_ABIERTO (opcional, por defecto false): si es true, las
      operaciones de CONTROL (mover, iniciar/cancelar DEMO y GET /sesion)
      se aceptan SIN clave. Crear, editar y eliminar siguen exigiendo la
      clave de operador o de administrador. Una clave incorrecta sigue
      respondiendo 401.
    """

    api_key_operador: str = field(repr=False)
    api_key_admin: str = field(repr=False)
    control_abierto: bool = False

    @classmethod
    def from_env(cls):
        operador = os.getenv("API_KEY_OPERADOR", "")
        admin = os.getenv("API_KEY_ADMIN", "")

        faltantes = [
            nombre
            for nombre, valor in (
                ("API_KEY_OPERADOR", operador),
                ("API_KEY_ADMIN", admin),
            )
            if not valor
        ]

        if faltantes:
            raise ValueError(
                "Faltan variables en el archivo .env: "
                + ", ".join(faltantes)
            )

        for nombre, valor in (
            ("API_KEY_OPERADOR", operador),
            ("API_KEY_ADMIN", admin),
        ):
            if len(valor) < LONGITUD_MINIMA_CLAVE_API:
                raise ValueError(
                    f"{nombre} debe tener al menos "
                    f"{LONGITUD_MINIMA_CLAVE_API} caracteres."
                )

        if operador == admin:
            raise ValueError(
                "API_KEY_OPERADOR y API_KEY_ADMIN deben ser distintas."
            )

        control_abierto = os.getenv("CONTROL_ABIERTO", "false").strip().lower() in VERDADERO

        return cls(
            api_key_operador=operador,
            api_key_admin=admin,
            control_abierto=control_abierto,
        )
