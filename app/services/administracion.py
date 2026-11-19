"""Servicios de ADMINISTRACIÓN (Etapa 3): modelos, unidades, usuarios,
asignaciones, auditoría y métricas.

- Validan ANTES de llamar al SP para responder 404/409 claros; los SP
  vuelven a comprobar las reglas dentro de su transacción (doble barrera).
- Cada alta, cambio, asignación o cambio de rol queda en la auditoría.
- Si la base aún no tiene V009, responden 503 (EsquemaPendiente) y el resto
  de la API (Control, Monitoreo) sigue funcionando igual.
- `actor` es quien hace la operación: el administrador con sesión (token,
  id_usuario real) o, en transición, la clave X-API-Key (id_usuario = None).
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

from app.core.exceptions import (
    ConflictoNegocio,
    ErrorAplicacion,
    EsquemaPendiente,
    RecursoNoEncontrado,
    SolicitudInvalida,
)

logger = logging.getLogger(__name__)

VERSION_ADMINISTRACION = 9
VERSION_AUTENTICACION = 10
VERSION_MAS_RECIENTE = VERSION_AUTENTICACION      # deja de consultarse al alcanzarla
ESTADOS = ("inventario", "vendida", "exhibicion", "baja")
_PATRON_CORREO = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


@dataclass(frozen=True)
class Actor:
    """Quién hace la operación (auditoría y asignado_por)."""

    id_usuario: Optional[int]
    rol: str                  # admin | usuario | invitado | operador | sistema
    via: str = "clave"        # clave (X-API-Key, transición) | token (Etapa 4)


def patron_busqueda(texto):
    """Texto para LIKE: escapa % y _ para que se busquen literalmente."""
    if texto is None or not texto.strip():
        return None
    return texto.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def pagina(registros, limite, desplazamiento):
    """Los SP de listado devuelven `total` (COUNT(*) OVER ()) en cada fila."""
    total = int(registros[0]["total"]) if registros else 0
    elementos = [{k: v for k, v in r.items() if k != "total"} for r in registros]
    return {"total": total, "limite": limite, "desplazamiento": desplazamiento, "elementos": elementos}


class EsquemaBD:
    """Versión de la base. Mientras no sea la más reciente que conoce el código,
    se vuelve a comprobar cada 30 s (así basta con aplicar la migración: no hay
    que reiniciar la API)."""

    REINTENTO_S = 30

    def __init__(self, repositorio):
        self.repositorio = repositorio
        self._version = None
        self._comprobado = 0.0

    def version(self):
        if self._version is not None and self._version >= VERSION_MAS_RECIENTE:
            return self._version
        ahora = time.monotonic()
        if self._version is not None and ahora - self._comprobado < self.REINTENTO_S:
            return self._version
        try:
            self._version = self.repositorio.version_esquema()
        except EsquemaPendiente:
            self._version = 0
        except ErrorAplicacion:
            return self._version or 0           # RDS caída: no se guarda el resultado
        self._comprobado = ahora
        return self._version

    def tiene_administracion(self):
        return self.version() >= VERSION_ADMINISTRACION

    def exigir(self):
        if not self.tiene_administracion():
            raise EsquemaPendiente()

    def tiene_autenticacion(self):
        return self.version() >= VERSION_AUTENTICACION

    def exigir_autenticacion(self):
        if not self.tiene_autenticacion():
            raise EsquemaPendiente(
                "La base aún no tiene la migración V010 (inicio de sesión). "
                "Aplícala con: python -m app.db.migrar aplicar --respaldo <snapshot>."
            )


class AuditoriaService:
    def __init__(self, repositorio, esquema):
        self.repositorio = repositorio
        self.esquema = esquema

    def registrar(self, actor, accion, recurso_tipo=None, recurso_id=None,
                  detalle=None, resultado="ok"):
        """Mejor esfuerzo: la operación ya se confirmó; si la bitácora falla se
        deja constancia en el log local y no se oculta el resultado al cliente."""
        if not self.esquema.tiene_administracion():
            return
        try:
            self.repositorio.registrar_auditoria(
                actor.id_usuario, actor.rol, accion, recurso_tipo,
                None if recurso_id is None else str(recurso_id), resultado,
                json.dumps(detalle, ensure_ascii=False, default=str) if detalle else None,
                None,
            )
        except ErrorAplicacion:
            logger.exception("No se pudo registrar la auditoría de %s", accion)

    def listar(self, accion, id_usuario, recurso_tipo, recurso_id, desde, hasta,
               limite, desplazamiento):
        self.esquema.exigir()
        registros = self.repositorio.listar_auditoria(
            accion, id_usuario, recurso_tipo, recurso_id, desde, hasta,
            limite, desplazamiento,
        )
        for r in registros:
            if isinstance(r.get("detalle"), (str, bytes)):
                try:
                    r["detalle"] = json.loads(r["detalle"])
                except ValueError:
                    pass
        return pagina(registros, limite, desplazamiento)


class ModeloService:
    def __init__(self, repositorio, esquema, auditoria):
        self.repositorio = repositorio
        self.esquema = esquema
        self.auditoria = auditoria

    def listar(self):
        self.esquema.exigir()
        return self.repositorio.listar_modelos()

    def obtener_o_fallar(self, id_modelo):
        self.esquema.exigir()
        modelo = self.repositorio.obtener_modelo(id_modelo)
        if modelo is None:
            raise RecursoNoEncontrado(f"El modelo {id_modelo} no existe.")
        return modelo

    def crear(self, actor, datos):
        self.esquema.exigir()
        id_modelo = self.repositorio.crear_modelo(
            datos.nombre.strip(), datos.descripcion, datos.microcontrolador,
            datos.max_movimiento_ms, datos.max_paso_ms, datos.max_pasos_demo, datos.max_demo_ms,
        )
        self.auditoria.registrar(actor, "modelo.crear", "modelo", id_modelo, {"nombre": datos.nombre})
        return self.obtener_o_fallar(id_modelo)

    def actualizar(self, actor, id_modelo, datos):
        antes = self.obtener_o_fallar(id_modelo)
        self.repositorio.actualizar_modelo(
            id_modelo, datos.nombre.strip(), datos.descripcion, datos.microcontrolador,
            datos.max_movimiento_ms, datos.max_paso_ms, datos.max_pasos_demo,
            datos.max_demo_ms, datos.activo,
        )
        despues = self.obtener_o_fallar(id_modelo)
        self.auditoria.registrar(actor, "modelo.actualizar", "modelo", id_modelo,
                                 _cambios(antes, despues))
        return despues

    def capacidades(self, id_modelo):
        self.obtener_o_fallar(id_modelo)
        return self.repositorio.listar_capacidades(id_modelo)

    def guardar_capacidad(self, actor, id_modelo, datos):
        actuales = self.capacidades(id_modelo)
        nombre = datos.nombre.strip().upper()
        for c in actuales:
            if c["nombre"].upper() == nombre and c["codigo"] != datos.codigo:
                raise ConflictoNegocio(f"El nombre {nombre} ya lo usa el código {c['codigo']}.")
        permitido = True if datos.tipo == "paro" else datos.permitido_invitado   # DETENER siempre disponible
        self.repositorio.guardar_capacidad(id_modelo, nombre, datos.codigo, datos.descripcion,
                                           datos.tipo, permitido)
        self.auditoria.registrar(actor, "capacidad.guardar", "modelo", id_modelo,
                                 {"codigo": datos.codigo, "nombre": nombre, "tipo": datos.tipo,
                                  "permitido_invitado": permitido})
        return next(c for c in self.repositorio.listar_capacidades(id_modelo) if c["codigo"] == datos.codigo)

    def eliminar_capacidad(self, actor, id_modelo, codigo):
        actual = next((c for c in self.capacidades(id_modelo) if c["codigo"] == codigo), None)
        if actual is None:
            raise RecursoNoEncontrado(f"El modelo {id_modelo} no tiene el código {codigo}.")
        if actual["tipo"] == "paro":
            raise ConflictoNegocio("La capacidad de paro (DETENER) no se puede eliminar: es la parada de seguridad.")
        self.repositorio.eliminar_capacidad(id_modelo, codigo)
        self.auditoria.registrar(actor, "capacidad.eliminar", "modelo", id_modelo,
                                 {"codigo": codigo, "nombre": actual["nombre"]})


class UnidadService:
    def __init__(self, repositorio, esquema, auditoria, modelos, demo_ejecutor):
        self.repositorio = repositorio
        self.esquema = esquema
        self.auditoria = auditoria
        self.modelos = modelos
        self.demo_ejecutor = demo_ejecutor

    def listar(self, estado, id_modelo, texto, limite, desplazamiento):
        self.esquema.exigir()
        if estado is not None and estado not in ESTADOS:
            raise SolicitudInvalida("Estado comercial inválido.")
        registros = self.repositorio.listar_unidades(
            estado, id_modelo, patron_busqueda(texto), limite, desplazamiento)
        return pagina(registros, limite, desplazamiento)

    def obtener_o_fallar(self, id_vehiculo):
        self.esquema.exigir()
        unidad = self.repositorio.obtener_unidad(id_vehiculo)
        if unidad is None:
            raise RecursoNoEncontrado(f"La unidad {id_vehiculo} no existe.")
        return unidad

    def crear(self, actor, datos):
        modelo = self.modelos.obtener_o_fallar(datos.id_modelo)
        if not modelo["activo"]:
            raise ConflictoNegocio(f"El modelo {modelo['nombre']} está inactivo.")
        id_vehiculo = self.repositorio.crear_unidad(
            datos.id_modelo, datos.nombre.strip(), datos.numero_serie, datos.descripcion,
            datos.estado_comercial, datos.es_simulada,
        )
        self.auditoria.registrar(actor, "unidad.crear", "unidad", id_vehiculo,
                                 {"modelo": modelo["nombre"], "numero_serie": datos.numero_serie,
                                  "estado": datos.estado_comercial, "simulada": datos.es_simulada})
        return self.obtener_o_fallar(id_vehiculo)

    def actualizar(self, actor, id_vehiculo, datos):
        antes = self.obtener_o_fallar(id_vehiculo)
        if (datos.estado_comercial == "vendida") != (antes["estado_comercial"] == "vendida"):
            raise ConflictoNegocio("El estado «vendida» solo cambia al asignar o finalizar una asignación.")
        if datos.estado_comercial == "baja" and antes["estado_comercial"] != "baja":
            raise ConflictoNegocio("Para dar de baja usa POST /admin/unidades/{id}/baja.")
        self.repositorio.actualizar_unidad(
            id_vehiculo, datos.nombre.strip(), datos.numero_serie, datos.descripcion,
            datos.estado_comercial, datos.activo,
        )
        despues = self.obtener_o_fallar(id_vehiculo)
        self.auditoria.registrar(actor, "unidad.actualizar", "unidad", id_vehiculo, _cambios(antes, despues))
        return despues

    def baja(self, actor, id_vehiculo):
        unidad = self.obtener_o_fallar(id_vehiculo)
        if unidad["estado_comercial"] == "baja":
            raise ConflictoNegocio("La unidad ya está dada de baja.")
        if self.demo_ejecutor.esta_ejecutando(id_vehiculo):
            raise ConflictoNegocio("La unidad tiene una DEMO en ejecución. Cancélala primero.")
        self.repositorio.baja_unidad(id_vehiculo)
        self.auditoria.registrar(actor, "unidad.baja", "unidad", id_vehiculo,
                                 {"estado_anterior": unidad["estado_comercial"]})
        return self.obtener_o_fallar(id_vehiculo)


class UsuarioService:
    def __init__(self, repositorio, esquema, auditoria):
        self.repositorio = repositorio
        self.esquema = esquema
        self.auditoria = auditoria

    @staticmethod
    def normalizar_correo(correo):
        correo = (correo or "").strip().lower()
        if not _PATRON_CORREO.match(correo) or len(correo) > 254:
            raise SolicitudInvalida("Correo electrónico inválido.")
        return correo

    def listar(self, rol, activo, texto, limite, desplazamiento):
        self.esquema.exigir()
        registros = self.repositorio.listar_usuarios(
            rol, activo, patron_busqueda(texto), limite, desplazamiento)
        return pagina(registros, limite, desplazamiento)

    def obtener_o_fallar(self, id_usuario):
        self.esquema.exigir()
        usuario = self.repositorio.obtener_usuario(id_usuario)
        if usuario is None:
            raise RecursoNoEncontrado(f"El usuario {id_usuario} no existe.")
        return usuario

    def crear(self, actor, datos):
        self.esquema.exigir()
        correo = self.normalizar_correo(datos.correo)
        try:
            id_usuario = self.repositorio.crear_usuario(correo, datos.nombre.strip(), datos.rol)
        except ConflictoNegocio as error:
            raise ConflictoNegocio("Ya existe un usuario con ese correo.") from error
        self.auditoria.registrar(actor, "usuario.crear", "usuario", id_usuario, {"correo": correo, "rol": datos.rol})
        return self.obtener_o_fallar(id_usuario)

    def actualizar(self, actor, id_usuario, datos):
        antes = self.obtener_o_fallar(id_usuario)
        self.repositorio.actualizar_usuario(id_usuario, datos.nombre.strip(), datos.rol, datos.activo)
        despues = self.obtener_o_fallar(id_usuario)
        self.auditoria.registrar(actor, "usuario.actualizar", "usuario", id_usuario, _cambios(antes, despues))
        if antes["rol"] != despues["rol"]:
            self.auditoria.registrar(actor, "rol.cambiar", "usuario", id_usuario,
                                     {"antes": antes["rol"], "despues": despues["rol"]})
        return despues


class AsignacionService:
    def __init__(self, repositorio, esquema, auditoria, unidades, usuarios, demo_ejecutor):
        self.repositorio = repositorio
        self.esquema = esquema
        self.auditoria = auditoria
        self.unidades = unidades
        self.usuarios = usuarios
        self.demo_ejecutor = demo_ejecutor

    def listar(self, id_vehiculo, id_usuario, solo_vigentes, limite, desplazamiento):
        self.esquema.exigir()
        registros = self.repositorio.listar_asignaciones(
            id_vehiculo, id_usuario, solo_vigentes, limite, desplazamiento)
        return pagina(registros, limite, desplazamiento)

    def asignar(self, actor, id_vehiculo, id_usuario):
        unidad = self.unidades.obtener_o_fallar(id_vehiculo)
        usuario = self.usuarios.obtener_o_fallar(id_usuario)
        if usuario["rol"] != "usuario" or not usuario["activo"]:
            raise ConflictoNegocio("Solo se puede asignar a un cliente activo.")
        if self.demo_ejecutor.esta_ejecutando(id_vehiculo):
            raise ConflictoNegocio("La unidad tiene una DEMO en ejecución. Cancélala primero.")
        id_asignacion = self.repositorio.asignar_unidad(id_vehiculo, id_usuario, actor.id_usuario)
        self.auditoria.registrar(actor, "asignacion.crear", "unidad", id_vehiculo,
                                 {"id_asignacion": id_asignacion, "cliente": usuario["correo"],
                                  "propietario_anterior": unidad.get("correo_propietario")})
        vigente = self.repositorio.listar_asignaciones(id_vehiculo, None, True, 1, 0)
        return {k: v for k, v in vigente[0].items() if k != "total"}

    def finalizar(self, actor, id_asignacion, motivo, estado_resultante):
        self.esquema.exigir()
        if estado_resultante not in ("inventario", "exhibicion", "baja"):
            raise SolicitudInvalida("Estado resultante inválido.")
        self.repositorio.finalizar_asignacion(id_asignacion, motivo, estado_resultante)
        self.auditoria.registrar(actor, "asignacion.finalizar", "asignacion", id_asignacion,
                                 {"motivo": motivo, "estado_resultante": estado_resultante})


class MetricasService:
    def __init__(self, repositorio, esquema):
        self.repositorio = repositorio
        self.esquema = esquema

    def obtener(self):
        self.esquema.exigir()
        return self.repositorio.metricas_admin()


def _cambios(antes, despues):
    """Solo los campos que cambiaron (para la auditoría)."""
    return {k: {"antes": antes.get(k), "despues": v}
            for k, v in despues.items() if antes.get(k) != v and k not in ("total",)}
