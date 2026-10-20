"""Capa de acceso a los 21 procedimientos almacenados de vehiculo_iot.

Responsabilidad única: ejecutar SP con parámetros enlazados y devolver
filas como diccionarios. Aquí NO hay reglas de negocio (eso vive en
app/services) ni código HTTP.
"""

import logging
from contextlib import contextmanager

import mysql.connector

from app.core.exceptions import (
    BaseDatosNoDisponible,
    ConflictoNegocio,
    ErrorBaseDatos,
    SolicitudInvalida,
)
from app.db.database import Database

logger = logging.getLogger(__name__)

# --- Los 21 procedimientos, agrupados -------------------------------------

PROCEDIMIENTOS_LECTURA = frozenset({
    "sp_obtener_vehiculos",
    "sp_obtener_vehiculo",
    "sp_obtener_comandos_vehiculo",
    "sp_obtener_estado",
    "sp_obtener_historial",
    "sp_obtener_demos",
    "sp_obtener_movimientos_demo",
})

PROCEDIMIENTOS_ESCRITURA = frozenset({
    "sp_crear_vehiculo",
    "sp_actualizar_vehiculo",
    "sp_eliminar_vehiculo",
    "sp_crear_comando",
    "sp_actualizar_comando",
    "sp_eliminar_comando",
    "sp_actualizar_estado",
    "sp_registrar_historial",
    "sp_crear_demo",
    "sp_actualizar_demo",
    "sp_eliminar_demo",
    "sp_agregar_movimiento_demo",
    "sp_actualizar_movimiento_demo",
    "sp_eliminar_movimiento_demo",
})

PROCEDIMIENTOS_PERMITIDOS = PROCEDIMIENTOS_LECTURA | PROCEDIMIENTOS_ESCRITURA

# Errores de MySQL que significan "no hay conexión / sin acceso".
_ERRNO_SIN_SERVICIO = {
    1040, 1044, 1045, 1049, 1129, 1130,
    2002, 2003, 2005, 2006, 2013, 2055,
}


def traducir_error_mysql(error):
    """Convierte un error de MySQL en una excepción de la aplicación.

    El detalle técnico se registra en el log local; nunca se devuelve al
    cliente (puede contener usuarios, hosts u otra información sensible).
    """

    errno = getattr(error, "errno", None)
    logger.error(
        "Error MySQL (errno=%s, sqlstate=%s): %s",
        errno,
        getattr(error, "sqlstate", None),
        getattr(error, "msg", error),
    )

    if errno == 1062:
        return ConflictoNegocio(
            "Ya existe un registro con esos valores únicos "
            "(por ejemplo nombre, código u orden repetidos)."
        )

    if errno == 1451:
        return ConflictoNegocio(
            "No se puede eliminar: el registro está siendo usado por "
            "otros datos (por ejemplo, un comando incluido en una DEMO)."
        )

    if errno == 1452:
        return SolicitudInvalida(
            "Una de las referencias indicadas (vehículo, comando o DEMO) "
            "no existe."
        )

    if errno in (1264, 1366, 1406):
        return SolicitudInvalida(
            "Alguno de los valores enviados excede el tamaño o el rango "
            "permitido."
        )

    if errno in _ERRNO_SIN_SERVICIO or isinstance(
        error, (mysql.connector.InterfaceError, OSError)
    ):
        return BaseDatosNoDisponible()

    return ErrorBaseDatos()


def _ejecutar_procedimiento(conexion, nombre, parametros):
    """Llama a un SP con parámetros enlazados y aplana sus resultados."""

    if nombre not in PROCEDIMIENTOS_PERMITIDOS:
        raise ValueError(f"Procedimiento no permitido: {nombre}")

    cursor = conexion.cursor()

    try:
        cursor.callproc(nombre, tuple(parametros))
        registros = []

        for resultado in cursor.stored_results():
            if resultado.description is None:
                continue

            columnas = [columna[0] for columna in resultado.description]

            for fila in resultado.fetchall():
                registros.append(dict(zip(columnas, fila)))

        return registros

    finally:
        cursor.close()


def _id_creado(registros, campo):
    if not registros or campo not in registros[0]:
        raise ErrorBaseDatos(
            "El procedimiento no devolvió el identificador creado."
        )

    return int(registros[0][campo])


class _ProcedimientosSP:
    """Un método por procedimiento almacenado.

    Las subclases solo deciden CÓMO se ejecuta cada llamada (conexión
    propia o transacción compartida) implementando _llamar().
    """

    def _llamar(self, nombre, parametros=()):
        raise NotImplementedError

    # ---------------- VEHÍCULOS ----------------

    def crear_vehiculo(self, nombre, modelo, descripcion, microcontrolador):
        registros = self._llamar(
            "sp_crear_vehiculo",
            (nombre, modelo, descripcion, microcontrolador),
        )
        return _id_creado(registros, "id_vehiculo")

    def obtener_vehiculos(self):
        return self._llamar("sp_obtener_vehiculos")

    def obtener_vehiculo(self, id_vehiculo):
        """Devuelve el vehículo (dict) o None si no existe."""
        registros = self._llamar("sp_obtener_vehiculo", (id_vehiculo,))
        return registros[0] if registros else None

    def actualizar_vehiculo(
        self, id_vehiculo, nombre, modelo, descripcion,
        microcontrolador, activo,
    ):
        self._llamar(
            "sp_actualizar_vehiculo",
            (id_vehiculo, nombre, modelo, descripcion,
             microcontrolador, activo),
        )

    def eliminar_vehiculo(self, id_vehiculo):
        self._llamar("sp_eliminar_vehiculo", (id_vehiculo,))

    # ---------------- COMANDOS ----------------

    def crear_comando(self, id_vehiculo, nombre, codigo, descripcion):
        registros = self._llamar(
            "sp_crear_comando",
            (id_vehiculo, nombre, codigo, descripcion),
        )
        return _id_creado(registros, "id_comando")

    def obtener_comandos_vehiculo(self, id_vehiculo):
        return self._llamar("sp_obtener_comandos_vehiculo", (id_vehiculo,))

    def actualizar_comando(
        self, id_comando, nombre, codigo, descripcion, activo,
    ):
        self._llamar(
            "sp_actualizar_comando",
            (id_comando, nombre, codigo, descripcion, activo),
        )

    def eliminar_comando(self, id_comando):
        self._llamar("sp_eliminar_comando", (id_comando,))

    # ---------------- ESTADO ----------------

    def actualizar_estado(self, id_vehiculo, id_comando, conectado):
        self._llamar(
            "sp_actualizar_estado",
            (id_vehiculo, id_comando, conectado),
        )

    def obtener_estado(self, id_vehiculo):
        """Devuelve el último estado (dict) o None si aún no existe."""
        registros = self._llamar("sp_obtener_estado", (id_vehiculo,))
        return registros[0] if registros else None

    # ---------------- HISTORIAL ----------------

    def registrar_historial(self, id_vehiculo, id_comando, origen):
        self._llamar(
            "sp_registrar_historial",
            (id_vehiculo, id_comando, origen),
        )

    def obtener_historial(self, id_vehiculo):
        """Historial completo, del más reciente al más antiguo."""
        return self._llamar("sp_obtener_historial", (id_vehiculo,))

    # ---------------- DEMOS ----------------

    def crear_demo(self, id_vehiculo, nombre, descripcion):
        registros = self._llamar(
            "sp_crear_demo",
            (id_vehiculo, nombre, descripcion),
        )
        return _id_creado(registros, "id_demo")

    def obtener_demos(self, id_vehiculo):
        return self._llamar("sp_obtener_demos", (id_vehiculo,))

    def actualizar_demo(self, id_demo, nombre, descripcion, activo):
        self._llamar(
            "sp_actualizar_demo",
            (id_demo, nombre, descripcion, activo),
        )

    def eliminar_demo(self, id_demo):
        self._llamar("sp_eliminar_demo", (id_demo,))

    # ---------------- MOVIMIENTOS DE DEMO ----------------

    def agregar_movimiento_demo(
        self, id_demo, id_comando, orden, duracion_ms, pausa_ms,
    ):
        self._llamar(
            "sp_agregar_movimiento_demo",
            (id_demo, id_comando, orden, duracion_ms, pausa_ms),
        )

    def obtener_movimientos_demo(self, id_demo):
        """Movimientos de la DEMO ordenados por el campo orden."""
        return self._llamar("sp_obtener_movimientos_demo", (id_demo,))

    def actualizar_movimiento_demo(
        self, id_demo_movimiento, id_comando, orden, duracion_ms, pausa_ms,
    ):
        self._llamar(
            "sp_actualizar_movimiento_demo",
            (id_demo_movimiento, id_comando, orden, duracion_ms, pausa_ms),
        )

    def eliminar_movimiento_demo(self, id_demo_movimiento):
        self._llamar("sp_eliminar_movimiento_demo", (id_demo_movimiento,))


class TransaccionSP(_ProcedimientosSP):
    """Ejecuta varios SP sobre UNA misma conexión/transacción."""

    def __init__(self, conexion):
        self._conexion = conexion

    def _llamar(self, nombre, parametros=()):
        try:
            return _ejecutar_procedimiento(self._conexion, nombre, parametros)
        except mysql.connector.Error as error:
            raise traducir_error_mysql(error) from error


class StoredProcedureRepository(_ProcedimientosSP):
    """Cada llamada abre su conexión; las escrituras se confirman solas."""

    def __init__(self, database=None):
        self.database = database or Database()

    def _llamar(self, nombre, parametros=()):
        try:
            with self.database.connection() as conexion:
                registros = _ejecutar_procedimiento(
                    conexion, nombre, parametros
                )

                # Las consultas (GET) nunca hacen commit: no modifican datos.
                if nombre in PROCEDIMIENTOS_ESCRITURA:
                    conexion.commit()

                return registros

        except mysql.connector.Error as error:
            raise traducir_error_mysql(error) from error

    def verificar(self):
        """Comprueba que RDS responde; 503 si no hay conexión."""

        try:
            return self.database.verificar()
        except mysql.connector.Error as error:
            raise traducir_error_mysql(error) from error

    @contextmanager
    def transaccion(self):
        """Varias llamadas atómicas: todo o nada.

        Uso:
            with repositorio.transaccion() as tx:
                tx.actualizar_estado(...)
                tx.registrar_historial(...)
            # <- aquí ya se hizo COMMIT (o ROLLBACK si hubo error)
        """

        try:
            with self.database.transaction() as conexion:
                yield TransaccionSP(conexion)

        except mysql.connector.Error as error:
            raise traducir_error_mysql(error) from error
