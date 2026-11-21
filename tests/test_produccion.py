"""Etapa 9 · Pruebas negativas y de contrato en MODO PRODUCCIÓN.

Configuración final: clave X-API-Key retirada, sin CONTROL_ABIERTO, sin
LECTURA_ABIERTA y sin WS_ABIERTO. Cada prueba corresponde a un caso de
prueba pedido en la tarea (ver docs/administracion/09-pruebas-y-publicacion.md).
"""

import time

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.config import AuthSettings
from tests.conftest import ADMIN, OPERADOR, SECRETO, construir_cliente
from tests.test_autenticacion import CLAVE, _bearer, _usuario
from tests.test_invitados import _abrir, _escenario, _inv, _reservar

PRODUCCION = {"auth": AuthSettings(secreto=SECRETO, lectura_abierta=False, ws_abierto=False),
              "control_abierto": False, "clave_habilitada": False}


@pytest.fixture
def prod(repo):
    with construir_cliente(repo, **PRODUCCION) as c:
        yield c


def _login(c, correo):
    r = c.post("/auth/login", json={"correo": correo, "contrasena": CLAVE})
    assert r.status_code == 200, r.text
    return _bearer(r.json())


def _mundo(repo, c):
    """Empresa, dos compradores con una unidad cada uno y una unidad de exhibición."""
    m = repo.crear_modelo("Modelo P", None, "ESP32", 3000, 5000, 10, 60000)
    repo.guardar_capacidad(m, "AVANZAR", 1, None, "movimiento", True)
    repo.guardar_capacidad(m, "LUZ", 10, None, "accesorio", False)
    repo.guardar_capacidad(m, "DETENER", 9, None, "paro", True)
    a, b = _usuario(repo, "a@ejemplo.com"), _usuario(repo, "b@ejemplo.com")
    _usuario(repo, "jefa@empresa.com", rol="admin")
    ua = repo.crear_unidad(m, "Unidad A", None, None, "inventario", False)
    ub = repo.crear_unidad(m, "Unidad B", None, None, "inventario", False)
    ve = repo.crear_unidad(m, "Exhibición", None, None, "exhibicion", False)
    repo.asignar_unidad(ua, a, None)
    repo.asignar_unidad(ub, b, None)
    return {"ua": ua, "ub": ub, "ve": ve, "a": a,
            "A": _login(c, "a@ejemplo.com"), "B": _login(c, "b@ejemplo.com"), "ADM": _login(c, "jefa@empresa.com")}


def _mover(c, v, codigo, cab=None):
    return c.post(f"/vehiculos/{v}/movimientos", json={"codigo": codigo}, headers=cab or {})


# ------------------------------------------------------------------ transición retirada

def test_transicion_retirada_clave_control_lectura_y_ws(repo, prod):
    w = _mundo(repo, prod)
    r = _mover(prod, w["ve"], 1, OPERADOR)
    assert r.status_code == 401 and "retiró" in r.json()["detail"]            # la clave ya no sirve
    assert prod.get("/admin/metricas", headers=ADMIN).status_code == 401
    assert prod.post("/vehiculos", json={"nombre": "x"}, headers=ADMIN).status_code == 401
    assert _mover(prod, w["ve"], 1).status_code == 401                          # sin CONTROL_ABIERTO
    assert prod.get(f"/vehiculos/{w['ve']}/historial").status_code == 401       # sin LECTURA_ABIERTA
    assert prod.get(f"/vehiculos/{w['ve']}/estado").status_code == 401
    with prod.websocket_connect(f"/ws/vehiculos/{w['ve']}") as ws:              # sin WS_ABIERTO
        assert ws.receive_json()["datos"]["codigo_error"] == "WS_NO_AUTORIZADO"
        with pytest.raises(WebSocketDisconnect) as cierre:
            ws.receive_json()
        assert cierre.value.code == 4401
    assert prod.post("/ws/ticket", json={"id_vehiculo": w["ve"]}).status_code == 401
    assert prod.get("/control").status_code == 410                              # panel de la clave retirado
    assert prod.get("/sesion").status_code == 401
    # Lo público sigue público: salud, catálogo de invitados e inicio de sesión
    assert prod.get("/health").status_code == 200
    assert prod.get("/invitado/catalogo").status_code == 200


# ------------------------------------------------------------------ casos de prueba de la tarea

def test_admin_registra_y_asigna_vehiculo(repo, prod):
    _usuario(repo, "jefa@empresa.com", rol="admin")
    adm = _login(prod, "jefa@empresa.com")
    m = prod.post("/admin/modelos", json={"nombre": "X9"}, headers=adm).json()["id_modelo"]
    assert prod.post(f"/admin/modelos/{m}/capacidades", json={"nombre": "AVANZAR", "codigo": 1}, headers=adm).status_code == 200
    u = prod.post("/admin/unidades", json={"id_modelo": m, "nombre": "Nueva", "numero_serie": "N-1"}, headers=adm).json()
    cli = prod.post("/admin/usuarios", json={"correo": "nuevo@ejemplo.com", "nombre": "Nuevo"}, headers=adm).json()
    r = prod.post("/admin/asignaciones", json={"id_vehiculo": u["id_vehiculo"], "id_usuario": cli["id_usuario"]}, headers=adm)
    assert r.status_code == 201 and r.json()["vigente"]
    assert prod.get(f"/admin/unidades/{u['id_vehiculo']}", headers=adm).json()["estado_comercial"] == "vendida"
    acciones = {a["accion"] for a in repo.auditoria}
    assert {"modelo.crear", "unidad.crear", "usuario.crear", "asignacion.crear"} <= acciones
    assert all(a["id_usuario"] is not None for a in repo.auditoria if a["accion"].endswith(".crear"))


def test_usuario_ve_solo_sus_unidades_y_controla(repo, prod):
    w = _mundo(repo, prod)
    assert [v["id_vehiculo"] for v in prod.get("/mis-vehiculos", headers=w["A"]).json()] == [w["ua"]]
    assert prod.get(f"/vehiculos/{w['ua']}/historial", headers=w["A"]).status_code == 200
    assert prod.get(f"/vehiculos/{w['ua']}/comandos", headers=w["A"]).status_code == 200
    assert _mover(prod, w["ua"], 1, w["A"]).status_code == 201
    ticket = prod.post("/ws/ticket", json={"id_vehiculo": w["ua"]}, headers=w["A"])
    assert ticket.status_code == 200 and ticket.json()["sujeto"]["tipo"] == "usuario"


def test_usuario_a_no_consulta_ni_ejecuta_lo_de_usuario_b(repo, prod):
    w = _mundo(repo, prod)
    ub, A = w["ub"], w["A"]
    d = prod.post(f"/mis-vehiculos/{ub}/demos", json={"nombre": "De B"}, headers=w["B"]).json()["id_demo"]
    lecturas = [f"/vehiculos/{ub}", f"/vehiculos/{ub}/estado", f"/vehiculos/{ub}/historial",
                f"/vehiculos/{ub}/comandos", f"/vehiculos/{ub}/demos", f"/vehiculos/{ub}/limites",
                f"/mis-vehiculos/{ub}/demos", f"/mis-vehiculos/{ub}/demos/{d}", f"/mis-vehiculos/{ub}/soporte"]
    for ruta in lecturas:
        assert prod.get(ruta, headers=A).status_code == 403, ruta
    assert _mover(prod, ub, 1, A).status_code == 403
    assert prod.post(f"/vehiculos/{ub}/demos/{d}/iniciar", headers=A).status_code == 403
    assert prod.post(f"/vehiculos/{ub}/demos/cancelar", headers=A).status_code == 403
    assert prod.post(f"/mis-vehiculos/{ub}/demos/{d}/pasos", json={"pasos": []}, headers=A).status_code == 403
    assert prod.post(f"/mis-vehiculos/{ub}/soporte", json={"horas": 1}, headers=A).status_code == 403
    assert prod.post("/ws/ticket", json={"id_vehiculo": ub}, headers=A).status_code == 403
    # Un comprador no entra a Administración
    for ruta in ("/admin/metricas", "/admin/unidades", "/admin/usuarios", "/admin/auditoria"):
        assert prod.get(ruta, headers=A).status_code == 403, ruta


def test_admin_sin_consentimiento_no_controla_unidad_vendida(repo, prod):
    w = _mundo(repo, prod)
    assert _mover(prod, w["ua"], 1, w["ADM"]).status_code == 403
    assert prod.get(f"/vehiculos/{w['ua']}/historial", headers=w["ADM"]).status_code == 403
    assert prod.post("/ws/ticket", json={"id_vehiculo": w["ua"]}, headers=w["ADM"]).status_code == 403
    assert prod.post(f"/mis-vehiculos/{w['ua']}/soporte", json={"horas": 1}, headers=w["A"]).status_code == 201
    assert _mover(prod, w["ua"], 1, w["ADM"]).status_code == 201                 # con consentimiento
    prod.post(f"/mis-vehiculos/{w['ua']}/soporte/revocar", headers=w["A"])
    assert _mover(prod, w["ua"], 1, w["ADM"]).status_code == 403                 # revocado
    assert _mover(prod, w["ve"], 1, w["ADM"]).status_code == 201                 # la de exhibición sí


def test_invitado_solo_opera_la_demo_temporal(repo, prod):
    w = _mundo(repo, prod)
    prod.post(f"/admin/unidades/{w['ve']}/exhibicion", json={"abierta": True, "horas": 1}, headers=w["ADM"])
    inv = {"X-Invitado": prod.post("/invitado/reservar", json={"id_vehiculo": w["ve"]}).json()["token_invitado"]}
    assert _mover(prod, w["ve"], 1, inv).status_code == 201
    assert _mover(prod, w["ve"], 10, inv).status_code == 403                     # comando no permitido
    assert _mover(prod, w["ua"], 1, inv).status_code == 403                      # nunca la de un comprador
    assert prod.get("/admin/metricas", headers=inv).status_code == 401           # nada privado
    assert prod.get("/mis-vehiculos", headers=inv).status_code == 401
    assert _mover(prod, w["ve"], 1, w["A"]).status_code == 403                   # nadie más mientras dura
    prod.post("/invitado/terminar", headers=inv)
    assert _mover(prod, w["ve"], 1, inv).status_code == 401                      # al terminar, nada


def test_wss_no_filtra_eventos_entre_usuarios(repo, prod):
    w = _mundo(repo, prod)
    tk = lambda v, cab: prod.post("/ws/ticket", json={"id_vehiculo": v}, headers=cab).json()["ticket"]  # noqa: E731
    with prod.websocket_connect(f"/ws/vehiculos/{w['ua']}?ticket={tk(w['ua'], w['A'])}") as wa, \
            prod.websocket_connect(f"/ws/vehiculos/{w['ub']}?ticket={tk(w['ub'], w['B'])}") as wb:
        wa.receive_json()
        wb.receive_json()
        _mover(prod, w["ub"], 1, w["B"])
        assert wb.receive_json()["id_vehiculo"] == w["ub"]
        _mover(prod, w["ua"], 9, w["A"])
        recibido = wa.receive_json()
        assert recibido["id_vehiculo"] == w["ua"] and recibido["comando"] == "DETENER"


def test_demos_persisten_y_se_ejecutan_con_detener(repo, prod):
    w = _mundo(repo, prod)
    ua, A = w["ua"], w["A"]
    d = prod.post(f"/mis-vehiculos/{ua}/demos", json={"nombre": "Rutina"}, headers=A).json()["id_demo"]
    pasos = [{"id_comando": 101, "duracion_ms": 4000}, {"id_comando": 101, "duracion_ms": 4000, "pausa_ms": 500}]
    prod.post(f"/mis-vehiculos/{ua}/demos/{d}/pasos", json={"pasos": pasos}, headers=A)
    guardada = prod.get(f"/mis-vehiculos/{ua}/demos/{d}", headers=A).json()             # persiste
    assert guardada["pasos"] == 2 and [m["duracion_ms"] for m in guardada["movimientos"]] == [4000, 4000]
    assert prod.post(f"/vehiculos/{ua}/demos/{d}/iniciar", headers=A).status_code == 202
    time.sleep(0.3)
    assert _mover(prod, ua, 1, A).status_code == 409                                   # durante la DEMO, no
    r = _mover(prod, ua, 9, A)                                                          # DETENER sí
    assert r.status_code == 201 and r.json()["comando"] == "DETENER"
    assert prod.get(f"/vehiculos/{ua}/demos/ejecucion", headers=A).json()["en_ejecucion"] is False


def test_rds_conserva_historial_y_su_autor(repo, prod):
    w = _mundo(repo, prod)
    _mover(prod, w["ua"], 1, w["A"])
    assert repo.historial_autor[-1] == (w["ua"], 101, w["a"])                          # quién movió
    r = prod.post(f"/admin/unidades/{w['ve']}/baja", headers=w["ADM"])
    assert r.status_code == 200 and r.json()["estado_comercial"] == "baja"              # baja, no borrado
    assert prod.post("/vehiculos/1/eliminar", headers=w["ADM"]).status_code == 409      # con historial no se borra


def test_reconexion_y_errores(repo, prod):
    w = _mundo(repo, prod)
    t = prod.post("/ws/ticket", json={"id_vehiculo": w["ua"]}, headers=w["A"]).json()["ticket"]
    with prod.websocket_connect(f"/ws/vehiculos/{w['ua']}?ticket={t}") as ws:
        assert ws.receive_json()["evento"] == "estado_inicial"
    with prod.websocket_connect(f"/ws/vehiculos/{w['ua']}?ticket={t}") as ws:          # reconectar con el mismo: no
        ws.receive_json()
        with pytest.raises(WebSocketDisconnect) as cierre:
            ws.receive_json()
        assert cierre.value.code == 4401                                                 # → el cliente pide otro
    nuevo = prod.post("/ws/ticket", json={"id_vehiculo": w["ua"]}, headers=w["A"]).json()["ticket"]
    with prod.websocket_connect(f"/ws/vehiculos/{w['ua']}?ticket={nuevo}") as ws:
        assert ws.receive_json()["evento"] == "estado_inicial"
    # Errores claros y sin detalles internos
    r = prod.get("/vehiculos/999999", headers=w["ADM"])
    assert r.status_code == 404 and "Traceback" not in r.text
    assert prod.get("/auth/yo", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401


def test_entradas_invalidas_y_maliciosas(repo, prod):
    w = _mundo(repo, prod)
    A, ADM = w["A"], w["ADM"]
    assert prod.post(f"/vehiculos/{w['ua']}/movimientos", json={"codigo": 1, "origen": "<script>"}, headers=A).status_code == 422
    assert prod.post(f"/vehiculos/{w['ua']}/movimientos", json={"codigo": 1, "id_comando": 101}, headers=A).status_code == 422
    assert prod.get("/vehiculos/0/historial", headers=A).status_code == 422
    assert prod.get("/vehiculos/-5/estado", headers=A).status_code == 422
    assert prod.post("/auth/login", json={"correo": "x" * 300, "contrasena": "y"}).status_code == 422
    # Búsquedas con caracteres de SQL: se tratan como texto literal
    for q in ("' OR 1=1 --", "%", "_", "\\"):
        r = prod.get("/admin/unidades", params={"q": q}, headers=ADM)
        assert r.status_code == 200 and r.json()["total"] == 0, q
    # Texto con HTML se guarda tal cual (la página lo pinta con textContent, nunca como HTML)
    r = prod.post(f"/mis-vehiculos/{w['ua']}/demos", json={"nombre": "<img src=x onerror=alert(1)>"}, headers=A)
    assert r.status_code == 201 and r.json()["nombre"] == "<img src=x onerror=alert(1)>"
    # Pasos de DEMO fuera de los límites del modelo
    d = r.json()["id_demo"]
    r = prod.post(f"/mis-vehiculos/{w['ua']}/demos/{d}/pasos",
                  json={"pasos": [{"id_comando": 101, "duracion_ms": 600000}]}, headers=A)
    assert r.status_code == 400


# ---- Ajustes posteriores: control completo del invitado y catálogo para la empresa

def test_invitado_lee_la_ejecucion_de_su_unidad_y_nada_mas(repo, prod):
    """Control completo del invitado: puede saber si corre una DEMO en SU unidad; no el historial ni otra unidad."""
    ve, uv, admin, _ = _escenario(repo, prod)
    _abrir(prod, ve, admin)
    h = _inv(_reservar(prod, ve).json()["token_invitado"])
    assert prod.get(f"/vehiculos/{ve}/demos/ejecucion", headers=h).status_code == 200
    assert prod.get(f"/vehiculos/{uv}/demos/ejecucion", headers=h).status_code == 403
    assert prod.get(f"/vehiculos/{ve}/historial", headers=h).status_code == 401      # el historial no se abre
    assert prod.post(f"/vehiculos/{ve}/movimientos", json={"codigo": 1, "origen": "WEB_JOYSTICK"},
                        headers=h).status_code == 201                                     # cualquier modo (origen)


def test_la_empresa_ve_el_catalogo_de_la_vendida_pero_no_su_historial(repo, prod):
    ve, uv, admin, comprador = _escenario(repo, prod)
    repo.unidades[uv]["estado_comercial"] = "vendida"
    assert prod.get(f"/vehiculos/{uv}/comandos", headers=admin).status_code == 200
    assert prod.get(f"/vehiculos/{uv}/historial", headers=admin).status_code == 403
    assert _mover(prod, uv, 1, admin).status_code == 403                               # sin soporte no la mueve
    assert prod.get(f"/vehiculos/{uv}/comandos", headers=comprador).status_code == 200
    assert prod.post(f"/vehiculos/{uv}/comandos/1/eliminar", headers=comprador).status_code == 403


def _id_cmd(repo, v, codigo):
    return next(c["id_comando"] for c in repo.comandos[v] if c["codigo"] == codigo)


def test_la_empresa_bloquea_movimientos_de_la_vendida_sin_soporte(repo, prod):
    """El administrador bloquea un movimiento de CUALQUIER unidad sin la autorización del cliente;
    el cliente deja de poder usarlo y no puede desbloquearlo. DETENER no se bloquea."""
    ve, uv, admin, comprador = _escenario(repo, prod)
    repo.unidades[uv]["estado_comercial"] = "vendida"
    avanzar, detener = _id_cmd(repo, uv, 1), _id_cmd(repo, uv, 9)
    url = f"/admin/unidades/{uv}/comandos/{avanzar}/bloqueo"
    assert _mover(prod, uv, 1, comprador).status_code == 201

    r = prod.post(url, json={"bloqueado": True}, headers=admin)                    # sin soporte del cliente
    assert r.status_code == 200, r.text
    assert r.json()["activo"] is False
    m = _mover(prod, uv, 1, comprador)
    assert m.status_code == 409 and "bloqueado" in m.json()["detail"]
    assert _mover(prod, uv, 9, comprador).status_code == 201                       # DETENER sigue
    assert prod.post(url, json={"bloqueado": False}, headers=comprador).status_code == 403
    assert prod.post(f"/vehiculos/{uv}/comandos/{avanzar}/actualizar", headers=comprador,
                     json={"nombre": "AVANZAR", "codigo": 1, "activo": True}).status_code == 403
    assert prod.post(url, json={"bloqueado": False}).status_code == 401
    r = prod.post(f"/admin/unidades/{uv}/comandos/{detener}/bloqueo", json={"bloqueado": True}, headers=admin)
    assert r.status_code == 409
    assert any(a["accion"] == "comando.bloquear" for a in repo.auditoria)

    assert prod.post(url, json={"bloqueado": False}, headers=admin).json()["activo"] is True
    assert _mover(prod, uv, 1, comprador).status_code == 201
    assert prod.post(f"/admin/unidades/{uv}/comandos/9999/bloqueo", json={"bloqueado": True},
                     headers=admin).status_code == 404


def test_el_bloqueo_alcanza_al_invitado_en_curso(repo, prod):
    ve, _, admin, _ = _escenario(repo, prod)
    _abrir(prod, ve, admin)
    h = _inv(_reservar(prod, ve).json()["token_invitado"])
    assert _mover(prod, ve, 1, h).status_code == 201
    assert prod.post(f"/admin/unidades/{ve}/comandos/{_id_cmd(repo, ve, 1)}/bloqueo",
                     json={"bloqueado": True}, headers=admin).status_code == 200
    assert 1 not in [c["codigo"] for c in prod.get("/invitado/estado", headers=h).json()["comandos"]]
    assert _mover(prod, ve, 1, h).status_code in (403, 409)
    assert _mover(prod, ve, 9, h).status_code == 201
