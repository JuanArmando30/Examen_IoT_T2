"""Capa de acceso a los procedimientos almacenados de vehiculo_iot.

Los 21 originales (prácticas 2.3/2.4), los 25 de ADMINISTRACIÓN (V009),
los 14 de AUTENTICACIÓN (V010), los 3 de DEMO PRIVADAS (V011) y los 6 de
INVITADOS (V012).
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
    EsquemaPendiente,
    SolicitudInvalida,
)
from app.db.database import Database

logger = logging.getLogger(__name__)

# --- Los 21 procedimientos originales, agrupados ---------------------------

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

PROCEDIMIENTOS_ORIGINALES = PROCEDIMIENTOS_LECTURA | PROCEDIMIENTOS_ESCRITURA

# --- V009 · Administración -------------------------------------------------

PROCEDIMIENTOS_V009_LECTURA = frozenset({
    "sp_version_esquema",
    "sp_obtener_historial_reciente",
    "sp_listar_auditoria",
    "sp_metricas_admin",
    "sp_listar_modelos",
    "sp_obtener_modelo",
    "sp_listar_capacidades",
    "sp_listar_unidades",
    "sp_obtener_unidad",
    "sp_listar_usuarios",
    "sp_obtener_usuario",
    "sp_listar_asignaciones",
    "sp_mis_vehiculos",
})

PROCEDIMIENTOS_V009_ESCRITURA = frozenset({
    "sp_registrar_auditoria",
    "sp_crear_modelo",
    "sp_actualizar_modelo",
    "sp_guardar_capacidad",
    "sp_eliminar_capacidad",
    "sp_crear_unidad",
    "sp_actualizar_unidad",
    "sp_baja_unidad",
    "sp_crear_usuario",
    "sp_actualizar_usuario",
    "sp_asignar_unidad",
    "sp_finalizar_asignacion",
})

# --- V010 · Autenticación y autorización por unidad ------------------------

PROCEDIMIENTOS_V010_LECTURA = frozenset({
    "sp_login_obtener",
    "sp_obtener_usuario_auth",
    "sp_acceso_unidad",
    "sp_soporte_listar",
})

PROCEDIMIENTOS_V010_ESCRITURA = frozenset({
    "sp_login_resultado",
    "sp_cambiar_contrasena",
    "sp_token_crear",
    "sp_token_usar",
    "sp_token_revocar",
    "sp_codigo_crear",
    "sp_codigo_usar",
    "sp_soporte_otorgar",
    "sp_soporte_revocar",
    "sp_registrar_historial_autor",
})

PROCEDIMIENTOS_V010 = PROCEDIMIENTOS_V010_LECTURA | PROCEDIMIENTOS_V010_ESCRITURA

# --- V011 · DEMO privadas y editor de pasos ---------------------------------

PROCEDIMIENTOS_V011_LECTURA = frozenset({"sp_limites_unidad"})
PROCEDIMIENTOS_V011_ESCRITURA = frozenset({"sp_crear_demo_privada", "sp_guardar_pasos_demo"})
PROCEDIMIENTOS_V011 = PROCEDIMIENTOS_V011_LECTURA | PROCEDIMIENTOS_V011_ESCRITURA

# --- V012 · Invitados y reserva de exhibición ----------------------------------

PROCEDIMIENTOS_V012_LECTURA = frozenset({"sp_catalogo_exhibicion", "sp_invitado_sesion", "sp_comandos_invitado"})
PROCEDIMIENTOS_V012_ESCRITURA = frozenset({"sp_invitado_reservar", "sp_invitado_finalizar", "sp_invitado_cerrar_todas"})
PROCEDIMIENTOS_V012 = PROCEDIMIENTOS_V012_LECTURA | PROCEDIMIENTOS_V012_ESCRITURA

PROCEDIMIENTOS_NUEVOS = (PROCEDIMIENTOS_V009_LECTURA | PROCEDIMIENTOS_V009_ESCRITURA
                         | PROCEDIMIENTOS_V010 | PROCEDIMIENTOS_V011 | PROCEDIMIENTOS_V012)
_ESCRITURA = (PROCEDIMIENTOS_ESCRITURA | PROCEDIMIENTOS_V009_ESCRITURA | PROCEDIMIENTOS_V010_ESCRITURA
              | PROCEDIMIENTOS_V011_ESCRITURA | PROCEDIMIENTOS_V012_ESCRITURA)
PROCEDIMIENTOS_PERMITIDOS = PROCEDIMIENTOS_ORIGINALES | PROCEDIMIENTOS_NUEVOS

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

    if errno == 1644:
        # SIGNAL SQLSTATE '45000' de los SP de V009: el mensaje lo escribimos
        # nosotros (regla de negocio) y no contiene datos sensibles.
        return ConflictoNegocio(getattr(error, "msg", None) or None)

    if errno == 3819:
        return SolicitudInvalida(
            "Algún valor no cumple las reglas de la base de datos "
            "(límites o valores permitidos)."
        )

    if errno == 1305:
        # Procedimiento inexistente: la base aún no tiene esa migración.
        return EsquemaPendiente()

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

    # ================= V009 · ADMINISTRACIÓN =================

    def version_esquema(self):
        """Versión de la base (0 si aún no se aplicó V009)."""
        registros = self._llamar("sp_version_esquema")
        return int(registros[0]["version"]) if registros else 0

    def obtener_historial_reciente(self, id_vehiculo, limite):
        return self._llamar("sp_obtener_historial_reciente", (id_vehiculo, limite))

    # ---------------- Auditoría y métricas ----------------

    def registrar_auditoria(self, id_usuario, rol_actor, accion, recurso_tipo,
                            recurso_id, resultado, detalle_json, red_hash):
        self._llamar("sp_registrar_auditoria", (
            id_usuario, rol_actor, accion, recurso_tipo, recurso_id,
            resultado, detalle_json, red_hash,
        ))

    def listar_auditoria(self, accion, id_usuario, recurso_tipo, recurso_id,
                         desde, hasta, limite, desplazamiento):
        return self._llamar("sp_listar_auditoria", (
            accion, id_usuario, recurso_tipo, recurso_id, desde, hasta,
            limite, desplazamiento,
        ))

    def metricas_admin(self):
        registros = self._llamar("sp_metricas_admin")
        return registros[0] if registros else {}

    # ---------------- Modelos y capacidades ----------------

    def listar_modelos(self):
        return self._llamar("sp_listar_modelos")

    def obtener_modelo(self, id_modelo):
        registros = self._llamar("sp_obtener_modelo", (id_modelo,))
        return registros[0] if registros else None

    def crear_modelo(self, nombre, descripcion, microcontrolador,
                     max_movimiento_ms, max_paso_ms, max_pasos_demo, max_demo_ms):
        registros = self._llamar("sp_crear_modelo", (
            nombre, descripcion, microcontrolador, max_movimiento_ms,
            max_paso_ms, max_pasos_demo, max_demo_ms,
        ))
        return _id_creado(registros, "id_modelo")

    def actualizar_modelo(self, id_modelo, nombre, descripcion, microcontrolador,
                          max_movimiento_ms, max_paso_ms, max_pasos_demo,
                          max_demo_ms, activo):
        self._llamar("sp_actualizar_modelo", (
            id_modelo, nombre, descripcion, microcontrolador, max_movimiento_ms,
            max_paso_ms, max_pasos_demo, max_demo_ms, activo,
        ))

    def listar_capacidades(self, id_modelo):
        return self._llamar("sp_listar_capacidades", (id_modelo,))

    def guardar_capacidad(self, id_modelo, nombre, codigo, descripcion, tipo,
                          permitido_invitado):
        self._llamar("sp_guardar_capacidad", (
            id_modelo, nombre, codigo, descripcion, tipo, permitido_invitado,
        ))

    def eliminar_capacidad(self, id_modelo, codigo):
        self._llamar("sp_eliminar_capacidad", (id_modelo, codigo))

    # ---------------- Unidades ----------------

    def listar_unidades(self, estado, id_modelo, texto, limite, desplazamiento):
        return self._llamar("sp_listar_unidades", (
            estado, id_modelo, texto, limite, desplazamiento,
        ))

    def obtener_unidad(self, id_vehiculo):
        registros = self._llamar("sp_obtener_unidad", (id_vehiculo,))
        return registros[0] if registros else None

    def crear_unidad(self, id_modelo, nombre, numero_serie, descripcion, estado,
                     es_simulada):
        registros = self._llamar("sp_crear_unidad", (
            id_modelo, nombre, numero_serie, descripcion, estado, es_simulada,
        ))
        return _id_creado(registros, "id_vehiculo")

    def actualizar_unidad(self, id_vehiculo, nombre, numero_serie, descripcion,
                          estado, activo):
        self._llamar("sp_actualizar_unidad", (
            id_vehiculo, nombre, numero_serie, descripcion, estado, activo,
        ))

    def baja_unidad(self, id_vehiculo):
        self._llamar("sp_baja_unidad", (id_vehiculo,))

    # ---------------- Usuarios ----------------

    def listar_usuarios(self, rol, activo, texto, limite, desplazamiento):
        return self._llamar("sp_listar_usuarios", (
            rol, activo, texto, limite, desplazamiento,
        ))

    def obtener_usuario(self, id_usuario):
        registros = self._llamar("sp_obtener_usuario", (id_usuario,))
        return registros[0] if registros else None

    def crear_usuario(self, correo, nombre, rol):
        registros = self._llamar("sp_crear_usuario", (correo, nombre, rol))
        return _id_creado(registros, "id_usuario")

    def actualizar_usuario(self, id_usuario, nombre, rol, activo):
        self._llamar("sp_actualizar_usuario", (id_usuario, nombre, rol, activo))

    # ---------------- Asignaciones ----------------

    def listar_asignaciones(self, id_vehiculo, id_usuario, solo_vigentes,
                            limite, desplazamiento):
        return self._llamar("sp_listar_asignaciones", (
            id_vehiculo, id_usuario, solo_vigentes, limite, desplazamiento,
        ))

    def asignar_unidad(self, id_vehiculo, id_usuario, asignado_por):
        registros = self._llamar("sp_asignar_unidad", (
            id_vehiculo, id_usuario, asignado_por,
        ))
        return _id_creado(registros, "id_asignacion")

    def finalizar_asignacion(self, id_asignacion, motivo, estado_resultante):
        self._llamar("sp_finalizar_asignacion", (
            id_asignacion, motivo, estado_resultante,
        ))

    def mis_vehiculos(self, id_usuario):
        return self._llamar("sp_mis_vehiculos", (id_usuario,))

    # ================= V010 · AUTENTICACIÓN =================

    def login_obtener(self, correo):
        """Fila con hash_contrasena y bloqueado, o None. El hash nunca sale de la API."""
        registros = self._llamar("sp_login_obtener", (correo,))
        return registros[0] if registros else None

    def login_resultado(self, id_usuario, exito, max_intentos, bloqueo_min):
        self._llamar("sp_login_resultado", (id_usuario, exito, max_intentos, bloqueo_min))

    def obtener_usuario_auth(self, id_usuario):
        registros = self._llamar("sp_obtener_usuario_auth", (id_usuario,))
        return registros[0] if registros else None

    def cambiar_contrasena(self, id_usuario, hash_contrasena):
        self._llamar("sp_cambiar_contrasena", (id_usuario, hash_contrasena))

    def token_crear(self, id_usuario, hash_token, familia, expira, agente):
        self._llamar("sp_token_crear", (id_usuario, hash_token, familia, expira, agente))

    def token_usar(self, hash_token, nuevo_hash, expira, agente):
        """Rota el token. Devuelve dict con «resultado» (+ datos del usuario si es ok)."""
        registros = self._llamar("sp_token_usar", (hash_token, nuevo_hash, expira, agente))
        return registros[0] if registros else {"resultado": "invalido"}

    def token_revocar(self, hash_token):
        self._llamar("sp_token_revocar", (hash_token,))

    def codigo_crear(self, id_usuario, hash_codigo, creado_por, expira):
        self._llamar("sp_codigo_crear", (id_usuario, hash_codigo, creado_por, expira))

    def codigo_usar(self, correo, hash_codigo, hash_contrasena, max_intentos):
        registros = self._llamar("sp_codigo_usar", (correo, hash_codigo, hash_contrasena, max_intentos))
        return registros[0] if registros else {"resultado": "invalido", "id_usuario": None}

    def acceso_unidad(self, id_usuario, id_vehiculo):
        """Relación usuario↔unidad, o None si la unidad no existe."""
        registros = self._llamar("sp_acceso_unidad", (id_usuario, id_vehiculo))
        return registros[0] if registros else None

    def soporte_otorgar(self, id_vehiculo, id_usuario, otorgada_a, motivo, expira):
        registros = self._llamar("sp_soporte_otorgar", (id_vehiculo, id_usuario, otorgada_a, motivo, expira))
        return _id_creado(registros, "id_autorizacion")

    def soporte_revocar(self, id_vehiculo, id_usuario):
        registros = self._llamar("sp_soporte_revocar", (id_vehiculo, id_usuario))
        return int(registros[0]["revocadas"]) if registros else 0

    def soporte_listar(self, id_vehiculo):
        return self._llamar("sp_soporte_listar", (id_vehiculo,))

    def registrar_historial_autor(self, id_vehiculo, id_comando, origen, id_usuario, id_sesion):
        self._llamar("sp_registrar_historial_autor", (id_vehiculo, id_comando, origen, id_usuario, id_sesion))

    # ================= V011 · DEMO PRIVADAS =================

    def limites_unidad(self, id_vehiculo):
        """Límites de seguridad de la unidad (de su modelo), o None si no existe."""
        registros = self._llamar("sp_limites_unidad", (id_vehiculo,))
        return registros[0] if registros else None

    def crear_demo_privada(self, id_vehiculo, id_usuario, nombre, descripcion):
        registros = self._llamar("sp_crear_demo_privada", (id_vehiculo, id_usuario, nombre, descripcion))
        return _id_creado(registros, "id_demo")

    def guardar_pasos_demo(self, id_demo, pasos_json):
        """Reemplaza todos los pasos (validados en el SP). Devuelve {pasos, duracion_total_ms}."""
        registros = self._llamar("sp_guardar_pasos_demo", (id_demo, pasos_json))
        return registros[0] if registros else {"pasos": 0, "duracion_total_ms": 0}

    # ================= V012 · INVITADOS =================

    def catalogo_exhibicion(self):
        return self._llamar("sp_catalogo_exhibicion")

    def invitado_reservar(self, id_vehiculo, hash_token, red_hash, minutos, max_por_hora, enfriamiento_min):
        """Devuelve {resultado: ok|no_disponible|ocupada|limite|enfriamiento, id_sesion, id_reserva, expira_en, segundos}."""
        registros = self._llamar("sp_invitado_reservar",
                                 (id_vehiculo, hash_token, red_hash, minutos, max_por_hora, enfriamiento_min))
        return registros[0] if registros else {"resultado": "no_disponible", "segundos": 0}

    def invitado_sesion(self, hash_token):
        registros = self._llamar("sp_invitado_sesion", (hash_token,))
        return registros[0] if registros else None

    def invitado_finalizar(self, id_reserva, motivo):
        registros = self._llamar("sp_invitado_finalizar", (id_reserva, motivo))
        return int(registros[0]["finalizadas"]) if registros else 0

    def invitado_cerrar_todas(self, motivo):
        registros = self._llamar("sp_invitado_cerrar_todas", (motivo,))
        return int(registros[0]["finalizadas"]) if registros else 0

    def comandos_invitado(self, id_vehiculo):
        return self._llamar("sp_comandos_invitado", (id_vehiculo,))


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
                if nombre in _ESCRITURA:
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
