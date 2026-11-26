"""Etapa 7: invitados anónimos y reserva temporal y exclusiva de la unidad de exhibición."""

import time
from datetime import timedelta

from tests.conftest import OPERADOR, RepositorioFalso, construir_cliente
from tests.test_autenticacion import _bearer, _usuario


def _escenario(repo, cliente):
    """Unidad de EXHIBICIÓN `ve` y unidad VENDIDA `uv` a un comprador; mismo modelo."""
    m = repo.crear_modelo("Modelo E7", None, "ESP32", 3000, 5000, 10, 60000)
    repo.guardar_capacidad(m, "AVANZAR", 1, None, "movimiento", True)
    repo.guardar_capacidad(m, "LUZ", 10, None, "accesorio", False)      # accesorio: igual va al invitado
    repo.guardar_capacidad(m, "GIRAR", 5, None, "movimiento", False)    # movimiento no permitido a invitados
    repo.guardar_capacidad(m, "DETENER", 9, None, "paro", True)
    ve = repo.crear_unidad(m, "Exhibición", None, None, "exhibicion", False)
    uv = repo.crear_unidad(m, "Vendida", None, None, "inventario", False)
    c = _usuario(repo, "c@ejemplo.com")
    _usuario(repo, "jefa@empresa.com", rol="admin")
    repo.asignar_unidad(uv, c, None)
    admin = _bearer(cliente.post("/auth/login", json={"correo": "jefa@empresa.com", "contrasena": "Contrasena123"}).json())
    comprador = _bearer(cliente.post("/auth/login", json={"correo": "c@ejemplo.com", "contrasena": "Contrasena123"}).json())
    return ve, uv, admin, comprador


def _abrir(cliente, ve, admin, horas=1):
    r = cliente.post(f"/admin/unidades/{ve}/exhibicion", json={"abierta": True, "horas": horas}, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def _reservar(cliente, ve):
    return cliente.post("/invitado/reservar", json={"id_vehiculo": ve})


def _inv(token):
    return {"X-Invitado": token}


def _mover(cliente, v, codigo, cabeceras):
    return cliente.post(f"/vehiculos/{v}/movimientos", json={"codigo": codigo, "origen": "WEB_INVITADO"}, headers=cabeceras)


def _esperar(condicion, segundos=4.0):
    fin = time.time() + segundos
    while time.time() < fin:
        if condicion():
            return True
        time.sleep(0.1)
    return False


def test_catalogo_y_exhibicion_cerrada_por_defecto(repo, cliente):
    ve, uv, admin, _ = _escenario(repo, cliente)
    cat = cliente.get("/invitado/catalogo").json()
    assert [u["id_vehiculo"] for u in cat] == [ve]                     # la vendida no aparece
    assert cat[0]["exhibicion_abierta"] is False and cat[0]["disponible"] is False
    r = _reservar(cliente, ve)
    assert r.status_code == 409 and "cerrada" in r.json()["detail"]


def test_reserva_exclusiva_y_comandos_permitidos(repo, cliente):
    ve, uv, admin, comprador = _escenario(repo, cliente)
    _abrir(cliente, ve, admin)
    r = _reservar(cliente, ve)
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    datos = r.json()
    token = datos["token_invitado"]
    assert token not in str(repo.reservas)                             # en la base solo su huella
    assert {c["codigo"] for c in datos["comandos"]} == {1, 9, 10} and 110 < datos["segundos_restantes"] <= 120  # 2 minutos
    assert next(c for c in datos["comandos"] if c["codigo"] == 10)["tipo"] == "accesorio"
    assert cliente.get("/invitado/catalogo").json()[0]["disponible"] is False
    assert _reservar(cliente, ve).status_code == 409                   # ocupada (sin fila)

    assert _mover(cliente, ve, 1, _inv(token)).status_code == 201      # AVANZAR permitido
    assert repo.historial_autor[-1][2] is None                         # sin usuario: el autor es la sesión
    assert _mover(cliente, ve, 5, _inv(token)).status_code == 403      # GIRAR no permitido a invitados
    assert _mover(cliente, ve, 10, _inv(token)).status_code == 201     # LUZ (accesorio) sí, como admin y cliente
    assert _mover(cliente, ve, 9, _inv(token)).status_code == 201      # DETENER siempre
    # Exclusividad: nadie más mueve la unidad durante la reserva… salvo DETENER
    assert _mover(cliente, ve, 1, OPERADOR).status_code == 409
    assert _mover(cliente, ve, 1, admin).status_code == 409
    assert _mover(cliente, ve, 9, OPERADOR).status_code == 201
    # El token del invitado no sirve para otra unidad (nunca la de un comprador)
    assert _mover(cliente, uv, 1, _inv(token)).status_code == 403
    assert _mover(cliente, uv, 1, comprador).status_code == 201        # el comprador sigue con la suya
    assert _mover(cliente, ve, 1, _inv("x" * 43)).status_code == 401   # token inventado


def test_no_se_reserva_ni_se_abre_una_unidad_vendida(repo, cliente):
    ve, uv, admin, _ = _escenario(repo, cliente)
    r = cliente.post(f"/admin/unidades/{uv}/exhibicion", json={"abierta": True, "horas": 1}, headers=admin)
    assert r.status_code == 409
    assert _reservar(cliente, uv).status_code == 409                   # cerrada / no disponible


def test_terminar_detiene_y_aplica_enfriamiento(repo, cliente):
    ve, uv, admin, _ = _escenario(repo, cliente)
    _abrir(cliente, ve, admin)
    token = _reservar(cliente, ve).json()["token_invitado"]
    assert cliente.post("/invitado/terminar", headers=_inv(token)).status_code == 204
    detener = next(c for c in repo.comandos[ve] if c["nombre"] == "DETENER")
    assert repo.estados[ve]["id_comando"] == detener["id_comando"]     # quedó en DETENER
    assert repo.reservas[-1]["motivo"] == "cancelada"
    assert _mover(cliente, ve, 1, _inv(token)).status_code == 401      # el token ya no sirve
    assert _mover(cliente, ve, 1, OPERADOR).status_code == 201         # la unidad quedó libre
    r = _reservar(cliente, ve)                                          # misma red, enseguida
    assert r.status_code == 429 and "de nuevo en 0:1" in r.json()["detail"]   # espera de 15 s (0:1x)
    assert repo.ultima_espera == 15
    assert {"invitado.reservar", "invitado.fin"} <= {a["accion"] for a in repo.auditoria}


def test_vigilante_por_caducidad_y_por_desconexion(repo, cliente):
    ve, uv, admin, _ = _escenario(repo, cliente)
    _abrir(cliente, ve, admin)
    servicio = cliente.app.state.contenedor.invitados
    _reservar(cliente, ve)
    servicio._activas[ve].expira -= timedelta(minutes=10)              # simula que pasaron los 5 min
    assert _esperar(lambda: ve not in servicio._activas)
    assert repo.reservas[-1]["motivo"] == "expirada"

    repo.reservas.clear()                                              # sin historial de red: puede reservar
    token = _reservar(cliente, ve).json()["token_invitado"]
    assert cliente.post("/invitado/latido", headers=_inv(token)).status_code == 200
    servicio._activas[ve].ultimo_latido -= 100                         # dejó de dar señales
    assert _esperar(lambda: ve not in servicio._activas)
    assert repo.reservas[-1]["motivo"] == "desconexion"


def test_demos_para_invitados(repo, cliente):
    ve, uv, admin, _ = _escenario(repo, cliente)
    ok = repo.crear_demo(ve, "Apta", None)
    repo.guardar_pasos_demo(ok, f'[{{"id_comando": {100 + 1}, "duracion_ms": 300, "pausa_ms": 0}}]')
    con_luz = repo.crear_demo(ve, "Con luz", None)
    repo.guardar_pasos_demo(con_luz, f'[{{"id_comando": {100 + 10}, "duracion_ms": 300, "pausa_ms": 0}}]')
    con_giro = repo.crear_demo(ve, "Con giro", None)
    repo.guardar_pasos_demo(con_giro, f'[{{"id_comando": {100 + 5}, "duracion_ms": 300, "pausa_ms": 0}}]')
    _abrir(cliente, ve, admin)
    datos = _reservar(cliente, ve).json()
    assert [d["nombre"] for d in datos["demos"]] == ["Apta", "Con luz"]  # la que usa GIRAR no se ofrece
    h = _inv(datos["token_invitado"])
    assert cliente.post(f"/vehiculos/{ve}/demos/{con_giro}/iniciar", headers=h).status_code == 403
    assert cliente.post(f"/vehiculos/{ve}/demos/{ok}/iniciar", headers=OPERADOR).status_code == 409
    assert cliente.post(f"/vehiculos/{ve}/demos/{ok}/iniciar", headers=h).status_code == 202
    time.sleep(0.5)


def test_la_empresa_cierra_o_termina_la_reserva(repo, cliente):
    ve, uv, admin, _ = _escenario(repo, cliente)
    _abrir(cliente, ve, admin)
    _reservar(cliente, ve)
    estado = cliente.get(f"/admin/unidades/{ve}/exhibicion", headers=admin).json()
    assert estado["abierta"] and estado["reserva"]["segundos_restantes"] > 0
    r = cliente.post(f"/admin/unidades/{ve}/exhibicion/terminar", headers=admin)
    assert r.status_code == 200 and r.json()["reserva"] is None and repo.reservas[-1]["motivo"] == "admin"
    assert cliente.post(f"/admin/unidades/{ve}/exhibicion/terminar", headers=admin).status_code == 409
    r = cliente.post(f"/admin/unidades/{ve}/exhibicion", json={"abierta": False}, headers=admin)
    assert r.status_code == 200 and r.json()["abierta"] is False
    assert {"exhibicion.abrir", "exhibicion.cerrar", "invitado.terminar"} <= {a["accion"] for a in repo.auditoria}


def test_espera_de_15_s_solo_con_v017():
    """Sin V017 el SP mide la espera en minutos: la API manda 1 (no 15, que serían 15 minutos)."""
    for version, esperado in ((16, 1), (17, 15)):
        repo = RepositorioFalso(version=version)
        with construir_cliente(repo) as cliente:
            ve, _, admin, _ = _escenario(repo, cliente)
            _abrir(cliente, ve, admin)
            token = _reservar(cliente, ve).json()["token_invitado"]
            cliente.post("/invitado/terminar", headers=_inv(token))
            assert _reservar(cliente, ve).status_code == 429
            assert repo.ultima_espera == esperado


def test_sin_v012_el_catalogo_da_503(repo, cliente):
    repo.version = 11
    cliente.app.state.contenedor.esquema._version = None
    assert cliente.get("/invitado/catalogo").status_code == 503


def test_reserva_propia_y_sin_espera_tras_desconexion(repo, cliente):
    """V014: la misma red ve «tu reserva» (no «ocupada») y una desconexión no castiga con espera."""
    ve, uv, admin, _ = _escenario(repo, cliente)
    _abrir(cliente, ve, admin)
    servicio = cliente.app.state.contenedor.invitados
    token = _reservar(cliente, ve).json()["token_invitado"]
    r = _reservar(cliente, ve)                                          # otra pestaña, misma red
    assert r.status_code == 409 and "Ya tienes una reserva" in r.json()["detail"]
    # El token sigue sirviendo (p. ej., tras recargar la página se reanuda con él)
    assert cliente.get("/invitado/estado", headers=_inv(token)).status_code == 200
    servicio._activas[ve].ultimo_latido -= 100                         # cerró la pestaña
    assert _esperar(lambda: ve not in servicio._activas)
    assert repo.reservas[-1]["motivo"] == "desconexion"
    assert _reservar(cliente, ve).status_code == 201                    # sin los 10 min de espera



def test_bitacora_registra_todo_lo_que_hace_el_invitado(repo, cliente):
    ve, uv, admin, comprador = _escenario(repo, cliente)
    demo = repo.crear_demo(ve, "Apta", None)
    repo.guardar_pasos_demo(demo, f'[{{"id_comando": {100 + 1}, "duracion_ms": 300, "pausa_ms": 0}}]')
    _abrir(cliente, ve, admin)
    datos = _reservar(cliente, ve).json()
    h, id_reserva = _inv(datos["token_invitado"]), datos["id_reserva"]
    for codigo, origen in ((1, "WEB_JOYSTICK"), (10, "WEB_BOTON"), (9, "WEB_PULSO")):
        assert cliente.post(f"/vehiculos/{ve}/movimientos", json={"codigo": codigo, "origen": origen},
                            headers=h).status_code == 201
    assert _mover(cliente, ve, 5, h).status_code == 403                 # rechazado: no se registra como hecho
    assert cliente.post(f"/vehiculos/{ve}/demos/{demo}/iniciar", headers=h).status_code == 202
    assert cliente.post(f"/vehiculos/{ve}/demos/cancelar", headers=h).status_code == 200
    assert cliente.post("/invitado/terminar", headers=_inv(datos["token_invitado"])).status_code == 204
    _mover(cliente, uv, 1, comprador)                                   # lo del comprador no entra como invitado

    filas = cliente.get("/admin/auditoria?accion=invitado.&limite=50", headers=admin).json()["elementos"]
    filas = list(reversed(filas))                                       # en orden de ocurrencia
    acciones = [f["accion"] for f in filas]
    assert acciones == ["invitado.reservar", "invitado.movimiento", "invitado.movimiento", "invitado.movimiento",
                        "invitado.demo", "invitado.demo_cancelar", "invitado.fin"], acciones
    movs = [f["detalle"] for f in filas if f["accion"] == "invitado.movimiento"]
    assert [(m["comando"], m["origen"]) for m in movs] == [("AVANZAR", "WEB_JOYSTICK"), ("LUZ", "WEB_BOTON"),
                                                            ("DETENER", "WEB_PULSO")]
    assert all(m["id_reserva"] == id_reserva for m in movs)
    assert all(f["rol_actor"] == "invitado" for f in filas if f["accion"] != "invitado.fin")
    assert filas[4]["detalle"]["nombre"] == "Apta"
    fin = filas[-1]["detalle"]
    assert fin["motivo"] == "cancelada" and fin["movimientos"] == 3 and fin["demos"] == 1 and fin["id_reserva"] == id_reserva
