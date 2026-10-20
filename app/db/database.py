import logging
from contextlib import contextmanager

import mysql.connector

from app.core.config import Settings

logger = logging.getLogger(__name__)


class Database:
    """Administra las conexiones a MySQL."""

    def __init__(self, config=None):
        self.config = config or Settings.from_env()

    def get_connection(self):
        """Abrir y devolver una conexión nueva a MySQL."""

        return mysql.connector.connect(
            host=self.config.db_host,
            port=self.config.db_port,
            database=self.config.db_name,
            user=self.config.db_user,
            password=self.config.db_password,
            charset="utf8mb4",
            autocommit=False,
            connection_timeout=5,
        )

    @contextmanager
    def connection(self):
        """Abrir una conexión y cerrarla al terminar."""

        conexion = None

        try:
            conexion = self.get_connection()
            yield conexion
        finally:
            if conexion is not None:
                conexion.close()

    @contextmanager
    def transaction(self):
        """Abrir una conexión con transacción atómica.

        Confirma (commit) si el bloque termina bien y deshace (rollback)
        si ocurre cualquier excepción. Siempre cierra la conexión.
        """

        with self.connection() as conexion:
            try:
                yield conexion
                conexion.commit()
            except Exception:
                try:
                    conexion.rollback()
                except mysql.connector.Error:
                    logger.warning("No fue posible hacer rollback.")
                raise

    def verificar(self) -> bool:
        """Comprobar que RDS responde (consulta fija, sin parámetros)."""

        with self.connection() as conexion:
            cursor = conexion.cursor()

            try:
                cursor.execute("SELECT 1")
                cursor.fetchall()
            finally:
                cursor.close()

        return True
