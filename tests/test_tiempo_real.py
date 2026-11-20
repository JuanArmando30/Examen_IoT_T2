"""Etapa 8: WebSocket por unidad con ticket, credencial del dispositivo, aislamiento y revocación.

Conexiones WebSocket REALES contra la API (TestClient).
"""

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.config import AuthSettings
from tests.conftest import OPERADOR, SECRETO, construir_cliente
from tests.test_autenticacion import _bearer, _usuario

CERRADO = {"auth": AuthSettings(secreto=SECRETO, ws_abierto=False)}


def _escenario(repo, cliente):
    m = repo.crear_modelo("Modelo E8", None, "ESP32", 3000, 5000, 10, 60000)
    repo.guardar_capacidad(m, "AVANZAR", 1, None, "movimiento", True)
    repo.guardar_capacidad(m, "DETENER", 9, None, "paro", True)
    a, b = _usuario(repo, "a@ejemplo.com"), _usuario(repo, "b@ejemplo.com")
    _usuario(repo, "jefa@empresa.com", rol="admin")
    ua = repo.crear_unidad(m, "Unidad A", None, None, "inventario", False)
    ub = repo.crear_unidad(m, "Unidad B", None, None, "inventario", False)
    ve = repo.crear_unidad(m, "Exhibición", None, None, "exhibicion", False)
    asig_a = repo.asignar_unidad(ua, a, None)
    repo.asignar_unidad(ub, b, None)
    h = {c.split("@")[0]: _bearer(cliente.post("/auth/login", json={"correo": c, "contrasena": "Contrasena123"}).json())
         for c in ("a@ejemplo.com", "b@ejemplo.com", "jefa@empresa.com")}
    return ua, ub, ve, asig_a, h


def _ticket(cliente, v, cabeceras):
    r = cliente.post("/ws/ticket", json={"id_vehiculo": v}, headers=cabeceras)
    assert r.status_code == 200, r.text
    return r.json()["ticket"]


def _rechazo(cliente, url, **kw):
    """Devuelve (evento de error, código de cierre) de una conexión rechazada."""
    with cliente.websocket_connect(url, **kw) as ws:
        error = ws.receive_json()
        with pytest.raises(WebSocketDisconnect) as cierre:
            ws.receive_json()
    return error, cierre.value.code


def _mover(cliente, v, codigo, cabeceras):
    return cliente.post(f"/vehiculos/{v}/movimientos", json={"codigo": codigo}, headers=cabeceras)


def test_transicion_ws_abierto_acepta_sin_ticket(repo, cliente):
    with cliente.websocket_connect("/ws/vehiculos/1") as ws:
        assert ws.receive_json()["evento"] == "estado_inicial"


def test_ws_cerrado_exige_ticket_y_lo_concede_con_las_reglas_de_rest(repo):
    with construir_cliente(repo, **CERRADO) as c:
        ua, ub, ve, _, h = _escenario(repo, c)
        error, codigo = _rechazo(c, f"/ws/vehiculos/{ua}")
        assert codigo == 4401 and error["datos"]["codigo_error"] == "WS_NO_AUTORIZADO"
        assert c.post("/ws/ticket", json={"id_vehiculo": ua}).status_code == 401          # sin credencial
        assert c.post("/ws/ticket", json={"id_vehiculo": ub}, headers=h["a"]).status_code == 403   # unidad ajena
        assert c.post("/ws/ticket", json={"id_vehiculo": ua}, headers=h["jefa"]).status_code == 403  # vendida sin soporte
        assert c.post("/ws/ticket", json={"id_vehiculo": ua}, headers={"X-API-Key": "mala-clave-123"}).status_code == 401
        t = _ticket(c, ua, h["a"])
        with c.websocket_connect(f"/ws/vehiculos/{ua}?ticket={t}") as ws:
            assert ws.receive_json()["evento"] == "estado_inicial"
        _, codigo = _rechazo(c, f"/ws/vehiculos/{ua}?ticket={t}")                         # un solo uso
        assert codigo == 4401
        _, codigo = _rechazo(c, f"/ws/vehiculos/{ub}?ticket={_ticket(c, ua, h['a'])}")    # ticket de otra unidad
        assert codigo == 4403
        assert c.post("/ws/ticket", json={"id_vehiculo": ve}, headers=OPERADOR).status_code == 200   # clave (transición)


def test_los_eventos_no_se_filtran_entre_usuarios(repo):
    with construir_cliente(repo, **CERRADO) as c:
        ua, ub, ve, _, h = _escenario(repo, c)
        with c.websocket_connect(f"/ws/vehiculos/{ua}?ticket={_ticket(c, ua, h['a'])}") as wa, \
                c.websocket_connect(f"/ws/vehiculos/{ub}?ticket={_ticket(c, ub, h['b'])}") as wb:
            wa.receive_json()
            wb.receive_json()
            assert _mover(c, ub, 1, h["b"]).status_code == 201
            ev_b = wb.receive_json()
            assert ev_b["evento"] == "movimiento_individual" and ev_b["id_vehiculo"] == ub
            assert _mover(c, ua, 9, h["a"]).status_code == 201
            ev_a = wa.receive_json()                  # lo primero que recibe A es SU movimiento, no el de B
            assert ev_a["id_vehiculo"] == ua and ev_a["comando"] == "DETENER"


def test_revocacion_al_perder_la_unidad(repo):
    with construir_cliente(repo, **CERRADO) as c:
        ua, ub, ve, asig_a, h = _escenario(repo, c)
        with c.websocket_connect(f"/ws/vehiculos/{ua}?ticket={_ticket(c, ua, h['a'])}") as wa:
            wa.receive_json()
            r = c.post(f"/admin/asignaciones/{asig_a}/finalizar", json={"estado_resultante": "inventario"}, headers=h["jefa"])
            assert r.status_code == 200, r.text
            assert c.portal.call(c.app.state.contenedor.canal.revalidar) == 1
            assert wa.receive_json()["datos"]["codigo_error"] == "WS_REVOCADO"
            with pytest.raises(WebSocketDisconnect) as cierre:
                wa.receive_json()
            assert cierre.value.code == 4403


def test_credencial_del_dispositivo_presencia_y_reportes(repo):
    with construir_cliente(repo, **CERRADO) as c:
        ua, ub, ve, _, h = _escenario(repo, c)
        r = c.post(f"/admin/unidades/{ve}/dispositivo", headers=h["jefa"])
        assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
        secreto = r.json()["secreto"]
        assert secreto not in str(repo.credenciales)                                    # solo su HMAC
        _, codigo = _rechazo(c, f"/ws/vehiculos/{ve}", headers={"X-Dispositivo": "dev_inventado_123456789"})
        assert codigo == 4401
        _, codigo = _rechazo(c, f"/ws/vehiculos/{ua}", headers={"X-Dispositivo": secreto})   # otra unidad
        assert codigo == 4403

        with c.websocket_connect(f"/ws/vehiculos/{ve}?ticket={_ticket(c, ve, h['jefa'])}") as obs:
            obs.receive_json()
            with c.websocket_connect(f"/ws/vehiculos/{ve}", headers={"X-Dispositivo": secreto}) as esp:
                ev = obs.receive_json()
                assert ev["evento"] == "estado_actualizado" and ev["datos"]["conectado"] is True   # presencia real
                assert esp.receive_json()["evento"] == "estado_inicial"
                assert c.get(f"/admin/unidades/{ve}/dispositivo", headers=h["jefa"]).json()["conectado"] is True
                esp.send_text('{"evento":"reporte","codigo":1,"accion":"ejecutando","duracion_ms":3000}')
                rep = obs.receive_json()
                assert rep["evento"] == "reporte_dispositivo" and rep["codigo"] == 1 and rep["datos"]["accion"] == "ejecutando"
                # Un navegador NO puede fingir reportes de la unidad
                obs.send_text('{"evento":"reporte","codigo":9,"accion":"detenido"}')
                obs.send_text("ping")
                assert obs.receive_json()["evento"] == "pong"
                # Revocar: el ESP32 queda fuera al instante y la unidad pasa a «desconectada»
                r = c.post(f"/admin/unidades/{ve}/dispositivo/revocar", headers=h["jefa"])
                assert r.status_code == 200 and r.json()["revocadas"] == 1 and r.json()["conectado"] is False
                recibidos = []
                with pytest.raises(WebSocketDisconnect) as cierre:
                    while True:                      # (el ESP32 también recibe las difusiones de su unidad)
                        recibidos.append(esp.receive_json())
                assert cierre.value.code == 4403
                assert recibidos[-1]["datos"].get("codigo_error") == "WS_REVOCADO"
            ev = obs.receive_json()
            assert ev["evento"] == "estado_actualizado" and ev["datos"]["conectado"] is False
        assert {"dispositivo.credencial", "dispositivo.revocar"} <= {a["accion"] for a in repo.auditoria}


def test_invitado_recibe_eventos_solo_mientras_dura_su_reserva(repo):
    with construir_cliente(repo, **CERRADO) as c:
        ua, ub, ve, _, h = _escenario(repo, c)
        c.post(f"/admin/unidades/{ve}/exhibicion", json={"abierta": True, "horas": 1}, headers=h["jefa"])
        token = c.post("/invitado/reservar", json={"id_vehiculo": ve}).json()["token_invitado"]
        inv = {"X-Invitado": token}
        assert c.post("/ws/ticket", json={"id_vehiculo": ua}, headers=inv).status_code == 403   # solo su unidad
        with c.websocket_connect(f"/ws/vehiculos/{ve}?ticket={_ticket(c, ve, inv)}") as ws:
            ws.receive_json()
            assert c.post("/invitado/terminar", headers=inv).status_code == 204
            mensajes = []
            with pytest.raises(WebSocketDisconnect) as cierre:
                while True:
                    mensajes.append(ws.receive_json())
            assert cierre.value.code == 4403
            assert any(m["evento"] == "error" and m["datos"]["codigo_error"] == "WS_REVOCADO" for m in mensajes)


def test_sin_v013_la_credencial_da_503(repo, cliente):
    ua, ub, ve, _, h = _escenario(repo, cliente)
    repo.version = 12
    cliente.app.state.contenedor.esquema._version = None
    assert cliente.post(f"/admin/unidades/{ve}/dispositivo", headers=h["jefa"]).status_code == 503
