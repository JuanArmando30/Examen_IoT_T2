"""Pruebas del backend sin base de datos: un repositorio falso en memoria
imita los procedimientos almacenados que usan las rutas. Las reglas de los
SP reales se prueban contra MySQL con `python -m app.db.migrar probar`.

Ejecutar:  python -m pytest -q
"""

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("API_KEY_OPERADOR", "clave-operador-123")
os.environ.setdefault("API_KEY_ADMIN", "clave-admin-12345")

from app.contenedor import Contenedor                      # noqa: E402
from app.core.config import SeguridadSettings               # noqa: E402
from app.core.exceptions import ConflictoNegocio, EsquemaPendiente  # noqa: E402
from app.main import crear_app                              # noqa: E402

CLAVE_OPERADOR = "clave-operador-123"
CLAVE_ADMIN = "clave-admin-12345"
ADMIN = {"X-API-Key": CLAVE_ADMIN}
OPERADOR = {"X-API-Key": CLAVE_OPERADOR}


class RepositorioFalso:
    """Lo mínimo de cada SP para probar rutas y servicios."""

    def __init__(self, con_v009=True):
        self.con_v009 = con_v009
        self.llamadas = []
        self.vehiculos = {1: {"id_vehiculo": 1, "nombre": "Excavadora IoT", "modelo": "Modelo X",
                              "descripcion": None, "microcontrolador": "ESP8266", "fecha_registro": None,
                              "activo": True}}
        self.historial = {1: [{"id_historial": n, "id_vehiculo": 1, "comando": "AVANZAR", "codigo": 1,
                               "fecha_hora": None, "origen": "WEB_PULSO"} for n in range(15, 0, -1)]}
        self.comandos = {1: [{"id_comando": 1, "id_vehiculo": 1, "nombre": "AVANZAR", "codigo": 1,
                              "descripcion": None, "activo": True}]}
        self.modelos, self.capacidades, self.unidades = {}, {}, {}
        self.usuarios, self.asignaciones, self.auditoria = {}, [], []
        self._ids = {"modelo": 0, "vehiculo": 1, "usuario": 0, "asignacion": 0}

    def _nuevo(self, tipo):
        self._ids[tipo] += 1
        return self._ids[tipo]

    def _anotar(self, nombre):
        self.llamadas.append(nombre)

    def _exigir(self):
        if not self.con_v009:
            raise EsquemaPendiente()

    # ---------------- originales usados por las pruebas ----------------
    def verificar(self):
        return True

    def obtener_vehiculo(self, id_vehiculo):
        return self.vehiculos.get(id_vehiculo)

    def obtener_vehiculos(self):
        return list(self.vehiculos.values())

    def obtener_historial(self, id_vehiculo):
        self._anotar("sp_obtener_historial")
        return list(self.historial.get(id_vehiculo, []))

    def obtener_comandos_vehiculo(self, id_vehiculo):
        return list(self.comandos.get(id_vehiculo, []))

    def obtener_estado(self, id_vehiculo):
        return None

    def obtener_demos(self, id_vehiculo):
        return []

    def eliminar_vehiculo(self, id_vehiculo):
        self._anotar("sp_eliminar_vehiculo")
        self.vehiculos.pop(id_vehiculo, None)

    # ---------------- V009 ----------------
    def version_esquema(self):
        self._exigir()
        return 9

    def obtener_historial_reciente(self, id_vehiculo, limite):
        self._exigir()
        self._anotar("sp_obtener_historial_reciente")
        return list(self.historial.get(id_vehiculo, []))[:limite]

    def registrar_auditoria(self, id_usuario, rol_actor, accion, recurso_tipo, recurso_id,
                            resultado, detalle_json, red_hash):
        self.auditoria.append({"id_auditoria": len(self.auditoria) + 1, "ocurrido_en": "2026-11-19T00:00:00",
                               "id_usuario": id_usuario, "usuario": None, "rol_actor": rol_actor,
                               "accion": accion, "recurso_tipo": recurso_tipo, "recurso_id": recurso_id,
                               "resultado": resultado, "detalle": detalle_json})

    def listar_auditoria(self, accion, id_usuario, recurso_tipo, recurso_id, desde, hasta, limite, desp):
        filas = [dict(a) for a in reversed(self.auditoria) if accion is None or a["accion"].startswith(accion)]
        return [{**f, "total": len(filas)} for f in filas[desp:desp + limite]]

    def metricas_admin(self):
        estados = [u["estado_comercial"] for u in self.unidades.values()]
        return {"unidades": len(self.unidades), "unidades_inventario": estados.count("inventario"),
                "unidades_vendidas": estados.count("vendida"), "unidades_exhibicion": estados.count("exhibicion"),
                "unidades_baja": estados.count("baja"),
                "unidades_simuladas": sum(1 for u in self.unidades.values() if u["es_simulada"]),
                "modelos_activos": len(self.modelos),
                "clientes_activos": sum(1 for u in self.usuarios.values() if u["rol"] == "usuario"),
                "administradores_activos": sum(1 for u in self.usuarios.values() if u["rol"] == "admin"),
                "asignaciones_vigentes": sum(1 for a in self.asignaciones if a["hasta"] is None),
                "demos_fabrica": 2, "demos_privadas": 0, "reservas_vigentes": 0, "movimientos_24h": 0,
                "movimientos_7d": 0, "movimientos_total": 15, "ultimo_movimiento": None,
                "generado_en": "2026-11-19T00:00:00"}

    def listar_modelos(self):
        return [self._modelo(i) for i in self.modelos]

    def _modelo(self, i):
        return {**self.modelos[i], "unidades": sum(1 for u in self.unidades.values() if u["id_modelo"] == i),
                "capacidades": len(self.capacidades.get(i, {}))}

    def obtener_modelo(self, id_modelo):
        return self._modelo(id_modelo) if id_modelo in self.modelos else None

    def crear_modelo(self, nombre, descripcion, micro, mov, paso, pasos, demo):
        i = self._nuevo("modelo")
        self.modelos[i] = {"id_modelo": i, "nombre": nombre, "descripcion": descripcion, "microcontrolador": micro,
                           "max_movimiento_ms": mov, "max_paso_ms": paso, "max_pasos_demo": pasos,
                           "max_demo_ms": demo, "activo": True, "fecha_registro": None}
        return i

    def actualizar_modelo(self, i, nombre, descripcion, micro, mov, paso, pasos, demo, activo):
        self.modelos[i].update(nombre=nombre, descripcion=descripcion, microcontrolador=micro, max_movimiento_ms=mov,
                               max_paso_ms=paso, max_pasos_demo=pasos, max_demo_ms=demo, activo=activo)

    def listar_capacidades(self, i):
        return sorted(self.capacidades.get(i, {}).values(), key=lambda c: c["codigo"])

    def guardar_capacidad(self, i, nombre, codigo, descripcion, tipo, permitido):
        self.capacidades.setdefault(i, {})[codigo] = {"id_modelo_comando": codigo, "id_modelo": i, "nombre": nombre,
                                                      "codigo": codigo, "descripcion": descripcion, "tipo": tipo,
                                                      "permitido_invitado": permitido}

    def eliminar_capacidad(self, i, codigo):
        self.capacidades.get(i, {}).pop(codigo, None)

    def _unidad(self, i):
        u = dict(self.unidades[i])
        vigente = next((a for a in self.asignaciones if a["id_vehiculo"] == i and a["hasta"] is None), None)
        dueno = self.usuarios.get(vigente["id_usuario"]) if vigente else None
        u.update(modelo=self.modelos[u["id_modelo"]]["nombre"], id_asignacion=vigente and vigente["id_asignacion"],
                 id_propietario=dueno and dueno["id_usuario"], propietario=dueno and dueno["nombre"],
                 correo_propietario=dueno and dueno["correo"], asignada_desde=None, conectado=None,
                 fecha_actualizacion=None)
        return u

    def listar_unidades(self, estado, id_modelo, texto, limite, desp):
        filas = [self._unidad(i) for i in sorted(self.unidades)
                 if (estado is None or self.unidades[i]["estado_comercial"] == estado)
                 and (id_modelo is None or self.unidades[i]["id_modelo"] == id_modelo)
                 and (texto is None or texto.lower() in self.unidades[i]["nombre"].lower())]
        return [{**f, "total": len(filas)} for f in filas[desp:desp + limite]]

    def obtener_unidad(self, i):
        return self._unidad(i) if i in self.unidades else None

    def crear_unidad(self, id_modelo, nombre, serie, descripcion, estado, simulada):
        i = self._nuevo("vehiculo")
        self.unidades[i] = {"id_vehiculo": i, "nombre": nombre, "numero_serie": serie, "estado_comercial": estado,
                            "es_simulada": simulada, "activo": True, "descripcion": descripcion,
                            "microcontrolador": self.modelos[id_modelo]["microcontrolador"],
                            "fecha_registro": None, "id_modelo": id_modelo}
        self.vehiculos[i] = {"id_vehiculo": i, "nombre": nombre, "activo": True}
        self.comandos[i] = [{"id_comando": 100 + c["codigo"], "id_vehiculo": i, "nombre": c["nombre"],
                             "codigo": c["codigo"], "descripcion": None, "activo": True}
                            for c in self.listar_capacidades(id_modelo)]
        return i

    def actualizar_unidad(self, i, nombre, serie, descripcion, estado, activo):
        self.unidades[i].update(nombre=nombre, numero_serie=serie, descripcion=descripcion,
                                estado_comercial=estado, activo=activo)

    def baja_unidad(self, i):
        self.unidades[i].update(estado_comercial="baja", activo=False)

    def listar_usuarios(self, rol, activo, texto, limite, desp):
        filas = [self.obtener_usuario(i) for i in sorted(self.usuarios)
                 if (rol is None or self.usuarios[i]["rol"] == rol)
                 and (activo is None or self.usuarios[i]["activo"] == activo)]
        return [{**f, "total": len(filas)} for f in filas[desp:desp + limite]]

    def obtener_usuario(self, i):
        if i not in self.usuarios:
            return None
        return {**self.usuarios[i], "creado_en": None, "ultimo_acceso": None, "tiene_contrasena": False,
                "unidades": sum(1 for a in self.asignaciones if a["id_usuario"] == i and a["hasta"] is None)}

    def crear_usuario(self, correo, nombre, rol):
        if any(u["correo"].lower() == correo.lower() for u in self.usuarios.values()):
            raise ConflictoNegocio("Ya existe un registro con esos valores únicos.")
        i = self._nuevo("usuario")
        self.usuarios[i] = {"id_usuario": i, "correo": correo, "nombre": nombre, "rol": rol, "activo": True}
        return i

    def actualizar_usuario(self, i, nombre, rol, activo):
        u = self.usuarios[i]
        otros_admins = [x for x in self.usuarios.values() if x["rol"] == "admin" and x["activo"] and x is not u]
        if u["rol"] == "admin" and (rol != "admin" or not activo) and not otros_admins:
            raise ConflictoNegocio("Es el único administrador activo: no se puede quitar su rol ni desactivarlo.")
        u.update(nombre=nombre, rol=rol, activo=activo)

    def _asignacion(self, a):
        v, u = self.unidades[a["id_vehiculo"]], self.usuarios[a["id_usuario"]]
        return {**a, "unidad": v["nombre"], "numero_serie": v["numero_serie"], "usuario": u["nombre"],
                "correo": u["correo"], "asignado_por_nombre": None, "vigente": a["hasta"] is None}

    def listar_asignaciones(self, id_vehiculo, id_usuario, vigentes, limite, desp):
        filas = [self._asignacion(a) for a in reversed(self.asignaciones)
                 if (id_vehiculo is None or a["id_vehiculo"] == id_vehiculo)
                 and (id_usuario is None or a["id_usuario"] == id_usuario)
                 and (not vigentes or a["hasta"] is None)]
        return [{**f, "total": len(filas)} for f in filas[desp:desp + limite]]

    def asignar_unidad(self, id_vehiculo, id_usuario, asignado_por):
        for a in self.asignaciones:
            if a["id_vehiculo"] == id_vehiculo and a["hasta"] is None:
                a.update(hasta="2026-11-19T00:00:00", motivo_fin="reasignada")
        i = self._nuevo("asignacion")
        self.asignaciones.append({"id_asignacion": i, "id_vehiculo": id_vehiculo, "id_usuario": id_usuario,
                                  "asignado_por": asignado_por, "desde": "2026-11-19T00:00:00", "hasta": None,
                                  "motivo_fin": None})
        self.unidades[id_vehiculo]["estado_comercial"] = "vendida"
        return i

    def finalizar_asignacion(self, id_asignacion, motivo, estado):
        a = next((x for x in self.asignaciones if x["id_asignacion"] == id_asignacion and x["hasta"] is None), None)
        if a is None:
            raise ConflictoNegocio("La asignación no existe o ya terminó.")
        a.update(hasta="2026-11-19T01:00:00", motivo_fin=motivo or "finalizada")
        self.unidades[a["id_vehiculo"]]["estado_comercial"] = estado


@pytest.fixture
def repo():
    return RepositorioFalso()


@pytest.fixture
def cliente(repo):
    seguridad = SeguridadSettings(CLAVE_OPERADOR, CLAVE_ADMIN, control_abierto=False)
    app = crear_app(lambda: Contenedor(repositorio=repo, seguridad=seguridad))
    with TestClient(app) as c:
        yield c
