"""Etapa 3 · rutas de ADMINISTRACIÓN y compatibilidad con la API existente."""

import json

from tests.conftest import ADMIN, OPERADOR, RepositorioFalso


def _modelo(cliente, **extra):
    datos = {"nombre": "Excavadora X1", "microcontrolador": "ESP32", **extra}
    r = cliente.post("/admin/modelos", json=datos, headers=ADMIN)
    assert r.status_code == 201, r.text
    return r.json()


def _unidad(cliente, id_modelo, nombre="Unidad A", **extra):
    r = cliente.post("/admin/unidades", json={"id_modelo": id_modelo, "nombre": nombre, **extra}, headers=ADMIN)
    assert r.status_code == 201, r.text
    return r.json()


def _usuario(cliente, correo, rol="usuario", nombre="Cliente"):
    r = cliente.post("/admin/usuarios", json={"correo": correo, "nombre": nombre, "rol": rol}, headers=ADMIN)
    assert r.status_code == 201, r.text
    return r.json()


# ----------------------------------------------------------------- Acceso

def test_admin_exige_clave_de_administrador(cliente):
    assert cliente.get("/admin/modelos").status_code == 401
    assert cliente.get("/admin/modelos", headers={"X-API-Key": "clave-equivocada-000"}).status_code == 401
    assert cliente.get("/admin/modelos", headers=OPERADOR).status_code == 403     # operador no administra
    assert cliente.get("/admin/modelos", headers=ADMIN).status_code == 200


def test_sin_v009_las_rutas_nuevas_dan_503_y_el_historial_sigue(repo, cliente):
    repo.con_v009 = False
    cliente.app.state.contenedor.esquema._version = None          # fuerza a volver a comprobar
    r = cliente.get("/admin/modelos", headers=ADMIN)
    assert r.status_code == 503 and "V001" in r.json()["detail"]
    h = cliente.get("/vehiculos/1/historial")
    assert h.status_code == 200 and h.json()["total_devueltos"] == 10
    assert "sp_obtener_historial" in repo.llamadas and "sp_obtener_historial_reciente" not in repo.llamadas


def test_con_v009_el_historial_usa_limit_en_la_base(repo, cliente):
    h = cliente.get("/vehiculos/1/historial")
    assert h.status_code == 200
    assert h.json()["total_devueltos"] == 10 and h.json()["limite"] == 10
    assert "sp_obtener_historial_reciente" in repo.llamadas


# ----------------------------------------------------------------- Modelos

def test_modelo_valida_limites(cliente):
    r = cliente.post("/admin/modelos", json={"nombre": "X", "max_paso_ms": 20000, "max_demo_ms": 10000}, headers=ADMIN)
    assert r.status_code == 422
    r = cliente.post("/admin/modelos", json={"nombre": "X", "max_paso_ms": 999999999}, headers=ADMIN)
    assert r.status_code == 422


def test_capacidades_paro_siempre_para_invitado_y_no_se_borra(cliente):
    m = _modelo(cliente)
    r = cliente.post(f"/admin/modelos/{m['id_modelo']}/capacidades",
                     json={"nombre": "detener", "codigo": 9, "tipo": "paro", "permitido_invitado": False}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["permitido_invitado"] is True and r.json()["nombre"] == "DETENER"
    r = cliente.post(f"/admin/modelos/{m['id_modelo']}/capacidades",
                     json={"nombre": "DETENER", "codigo": 99}, headers=ADMIN)
    assert r.status_code == 409                                   # mismo nombre con otro código
    r = cliente.post(f"/admin/modelos/{m['id_modelo']}/capacidades/9/eliminar", headers=ADMIN)
    assert r.status_code == 409                                   # DETENER no se elimina
    r = cliente.post(f"/admin/modelos/{m['id_modelo']}/capacidades/5/eliminar", headers=ADMIN)
    assert r.status_code == 404


# ----------------------------------------------------------------- Unidades

def test_unidad_nace_con_el_catalogo_del_modelo(repo, cliente):
    m = _modelo(cliente)
    for nombre, codigo, tipo in (("AVANZAR", 1, "movimiento"), ("DETENER", 9, "paro")):
        cliente.post(f"/admin/modelos/{m['id_modelo']}/capacidades",
                     json={"nombre": nombre, "codigo": codigo, "tipo": tipo}, headers=ADMIN)
    u = _unidad(cliente, m["id_modelo"], numero_serie="SIM-0002", es_simulada=True)
    assert u["estado_comercial"] == "inventario" and u["es_simulada"] is True and u["modelo"] == "Excavadora X1"
    assert {c["codigo"] for c in repo.comandos[u["id_vehiculo"]]} == {1, 9}
    # La API existente ve la unidad como un vehículo más (mismo ID)
    assert cliente.get(f"/vehiculos/{u['id_vehiculo']}/comandos").status_code == 200


def test_unidad_no_nace_vendida_ni_se_vende_a_mano(cliente):
    m = _modelo(cliente)
    r = cliente.post("/admin/unidades", json={"id_modelo": m["id_modelo"], "nombre": "x",
                                              "estado_comercial": "vendida"}, headers=ADMIN)
    assert r.status_code == 422
    u = _unidad(cliente, m["id_modelo"])
    r = cliente.post(f"/admin/unidades/{u['id_vehiculo']}/actualizar",
                     json={"nombre": "x", "estado_comercial": "vendida"}, headers=ADMIN)
    assert r.status_code == 409


def test_inventario_paginado(cliente):
    m = _modelo(cliente)
    for n in range(5):
        _unidad(cliente, m["id_modelo"], nombre=f"Unidad {n}")
    r = cliente.get("/admin/unidades?limite=2&desplazamiento=2", headers=ADMIN)
    cuerpo = r.json()
    assert r.status_code == 200 and cuerpo["total"] == 5 and len(cuerpo["elementos"]) == 2
    assert cuerpo["limite"] == 2 and cuerpo["desplazamiento"] == 2
    assert cliente.get("/admin/unidades?limite=500", headers=ADMIN).status_code == 422


def test_baja_en_lugar_de_borrar(cliente):
    m = _modelo(cliente)
    u = _unidad(cliente, m["id_modelo"])
    r = cliente.post(f"/admin/unidades/{u['id_vehiculo']}/baja", headers=ADMIN)
    assert r.status_code == 200 and r.json()["estado_comercial"] == "baja" and r.json()["activo"] is False
    assert cliente.post(f"/admin/unidades/{u['id_vehiculo']}/baja", headers=ADMIN).status_code == 409


def test_borrar_vehiculo_con_historial_se_rechaza_con_v009(repo, cliente):
    r = cliente.post("/vehiculos/1/eliminar", headers=ADMIN)
    assert r.status_code == 409 and "baja" in r.json()["detail"]
    assert "sp_eliminar_vehiculo" not in repo.llamadas


# ----------------------------------------------------------------- Usuarios

def test_usuario_correo_normalizado_unico_y_valido(cliente):
    u = _usuario(cliente, "  Cliente.Uno@Ejemplo.COM ")
    assert u["correo"] == "cliente.uno@ejemplo.com" and u["tiene_contrasena"] is False
    assert cliente.post("/admin/usuarios", json={"correo": "CLIENTE.UNO@ejemplo.com", "nombre": "x"},
                        headers=ADMIN).status_code == 409
    assert cliente.post("/admin/usuarios", json={"correo": "sin-arroba", "nombre": "x"},
                        headers=ADMIN).status_code == 400


def test_ultimo_admin_protegido_y_cambio_de_rol_auditado(repo, cliente):
    a = _usuario(cliente, "admin@ejemplo.com", rol="admin", nombre="Admin")
    r = cliente.post(f"/admin/usuarios/{a['id_usuario']}/actualizar",
                     json={"nombre": "Admin", "rol": "usuario", "activo": True}, headers=ADMIN)
    assert r.status_code == 409
    _usuario(cliente, "admin2@ejemplo.com", rol="admin", nombre="Admin 2")
    r = cliente.post(f"/admin/usuarios/{a['id_usuario']}/actualizar",
                     json={"nombre": "Admin", "rol": "usuario", "activo": True}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["rol"] == "usuario"
    assert any(x["accion"] == "rol.cambiar" for x in repo.auditoria)


# ----------------------------------------------------------------- Asignaciones

def test_asignar_y_finalizar(repo, cliente):
    m = _modelo(cliente)
    u = _unidad(cliente, m["id_modelo"])
    c1 = _usuario(cliente, "c1@ejemplo.com")
    c2 = _usuario(cliente, "c2@ejemplo.com")
    admin = _usuario(cliente, "a@ejemplo.com", rol="admin")
    assert cliente.post("/admin/asignaciones", json={"id_vehiculo": u["id_vehiculo"], "id_usuario": admin["id_usuario"]},
                        headers=ADMIN).status_code == 409             # solo a clientes
    r = cliente.post("/admin/asignaciones", json={"id_vehiculo": u["id_vehiculo"], "id_usuario": c1["id_usuario"]},
                     headers=ADMIN)
    assert r.status_code == 201 and r.json()["vigente"] is True and r.json()["asignado_por"] is None
    assert cliente.get(f"/admin/unidades/{u['id_vehiculo']}", headers=ADMIN).json()["estado_comercial"] == "vendida"
    # Reasignar a otro cliente cierra la anterior: un solo dueño vigente
    r2 = cliente.post("/admin/asignaciones", json={"id_vehiculo": u["id_vehiculo"], "id_usuario": c2["id_usuario"]},
                      headers=ADMIN)
    vigentes = cliente.get(f"/admin/asignaciones?id_vehiculo={u['id_vehiculo']}&vigentes=true", headers=ADMIN).json()
    assert vigentes["total"] == 1 and vigentes["elementos"][0]["id_usuario"] == c2["id_usuario"]
    r = cliente.post(f"/admin/asignaciones/{r2.json()['id_asignacion']}/finalizar",
                     json={"motivo": "devolución", "estado_resultante": "exhibicion"}, headers=ADMIN)
    assert r.status_code == 200
    assert cliente.get(f"/admin/unidades/{u['id_vehiculo']}", headers=ADMIN).json()["estado_comercial"] == "exhibicion"
    assert cliente.post(f"/admin/asignaciones/{r2.json()['id_asignacion']}/finalizar", json={},
                        headers=ADMIN).status_code == 409
    acciones = [x["accion"] for x in repo.auditoria]
    assert acciones.count("asignacion.crear") == 2 and "asignacion.finalizar" in acciones


# ----------------------------------------------------------------- Auditoría y métricas

def test_auditoria_paginada_y_detalle_como_json(repo, cliente):
    _modelo(cliente)
    r = cliente.get("/admin/auditoria?accion=modelo.", headers=ADMIN)
    cuerpo = r.json()
    assert r.status_code == 200 and cuerpo["total"] == 1
    entrada = cuerpo["elementos"][0]
    assert entrada["accion"] == "modelo.crear" and entrada["rol_actor"] == "admin"
    assert entrada["detalle"] == {"nombre": "Excavadora X1"}                 # JSON ya convertido
    assert json.loads(repo.auditoria[0]["detalle"]) == {"nombre": "Excavadora X1"}


def test_metricas(cliente):
    m = _modelo(cliente)
    _unidad(cliente, m["id_modelo"], es_simulada=True)
    r = cliente.get("/admin/metricas", headers=ADMIN)
    assert r.status_code == 200 and r.json()["unidades"] == 1 and r.json()["unidades_simuladas"] == 1


# ----------------------------------------------------------------- Compatibilidad

def test_las_rutas_previas_siguen_en_swagger(cliente):
    rutas = cliente.get("/openapi.json").json()["paths"]
    previas = ["/", "/health", "/health/db", "/sesion", "/vehiculos", "/vehiculos/{id_vehiculo}",
               "/vehiculos/{id_vehiculo}/movimientos", "/vehiculos/{id_vehiculo}/historial",
               "/vehiculos/{id_vehiculo}/estado", "/vehiculos/{id_vehiculo}/demos",
               "/vehiculos/{id_vehiculo}/demos/{id_demo}/iniciar", "/vehiculos/{id_vehiculo}/demos/cancelar"]
    assert all(p in rutas for p in previas)
    operaciones = sum(len(v) for v in rutas.values())
    nuevas = sum(len(v) for k, v in rutas.items() if k.startswith("/admin"))
    sesion = sum(len(v) for k, v in rutas.items() if k.startswith(("/auth", "/mis-vehiculos")))
    # Etapa 3: 21 /admin · Etapa 4: +1 /admin y 10 de sesión · Etapa 6: +1 /admin, +6 mis DEMO, +1 límites
    assert nuevas == 23 and sesion == 16 and operaciones == 28 + 1 + 23 + 16


def test_repositorio_falso_no_v009_por_defecto_es_coherente():
    assert RepositorioFalso(con_v009=False).con_v009 is False
