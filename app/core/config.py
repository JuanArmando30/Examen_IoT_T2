import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


# Ruta de la carpeta raíz del proyecto
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Cargar las variables del archivo .env
load_dotenv(PROJECT_ROOT / ".env")

LONGITUD_MINIMA_CLAVE_API = 12


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
    """

    api_key_operador: str = field(repr=False)
    api_key_admin: str = field(repr=False)

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

        return cls(api_key_operador=operador, api_key_admin=admin)
