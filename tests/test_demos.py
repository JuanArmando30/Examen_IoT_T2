"""Etapa 6: DEMO privadas, editor de pasos, límites del modelo y prioridad de DETENER."""

import time

from tests.conftest import ADMIN, OPERADOR
from tests.test_autenticacion import _bearer, _usuario


def _escenario(repo, cliente):
    """Modelo con límites pequeños, una unidad vendida a A y otra a B."""
    m = repo.crear_modelo("Modelo E6", None, "ESP32", 3000, 5000, 3, 9000)
    for cod, nom, tipo in [(1, "AVANZAR", "movimiento"), (2, "RETROCEDER", "movimiento"), (9, "DETENER", "paro")]:
        repo.guardar_capacidad(m, nom, cod, None, tipo, True)
    a, b = _usuario(repo, "a@ejemplo.com"), _usuario(repo, "b@ejemplo.com")
    _usuario(repo, "jefa@empresa.com", rol="admin")
    ua = repo.crear_unidad(m, "Unidad A", None, None, "inventario", False)
    ub = repo.crear_unidad(m, "Unidad B", None, None, "inventario", False)
    repo.asignar_unidad(ua, a, None)
    repo.asignar_unidad(ub, b, None)
    fabrica = repo.crear_demo(ua, "Fábrica", None)
    repo.guardar_pasos_demo(fabrica, '[{"id_comando": 101, "duracion_ms": 1000, "pausa_ms": 0}]')
    sesiones = {c: cliente.post("/auth/login", json={"correo": c, "contrasena": "Contrasena123"}).json()
                for c in ("a@ejemplo.com", "b@ejemplo.com", "jefa@empresa.com")}
    return ua, ub, fabrica, {k.split("@")[0]: _bearer(v) for k, v in sesiones.items()}


def test_comprador_crea_y_edita_su_demo_privada(repo, cliente):
    ua, ub, fabrica, h = _escenario(repo, cliente)
    r = cliente.post(f"/mis-vehiculos/{ua}/demos", json={"nombre": " Mi rutina ", "descripcion": "x"}, headers=h["a"])
    assert r.status_code == 201 and r.json()["ambito"] == "privada" and r.json()["propia"] and r.json()["nombre"] == "Mi rutina"
    d = r.json()["id_demo"]
    pasos = [{"id_comando": 101, "duracion_ms": 1500, "pausa_ms": 300}, {"id_comando": 102, "duracion_ms": 800}]
    r = cliente.post(f"/mis-vehiculos/{ua}/demos/{d}/pasos", json={"pasos": pasos}, headers=h["a"])
    assert r.status_code == 200 and r.json()["pasos"] == 2 and r.json()["duracion_total_ms"] == 2600
    # Reordenar = guardar la lista en otro orden
    r = cliente.post(f"/mis-vehiculos/{ua}/demos/{d}/pasos", json={"pasos": pasos[::-1]}, headers=h["a"])
    assert [m["comando"] for m in r.json()["movimientos"]] == ["RETROCEDER", "AVANZAR"]
    lista = cliente.get(f"/mis-vehiculos/{ua}/demos", headers=h["a"]).json()
    assert {(x["nombre"], x["ambito"], x["propia"]) for x in lista} == {("Fábrica", "fabrica", False), ("Mi rutina", "privada", True)}
    r = cliente.post(f"/mis-vehiculos/{ua}/demos/{d}/actualizar", json={"nombre": "Otra", "activo": False}, headers=h["a"])
    assert r.status_code == 200 and r.json()["activo"] is False
    assert {"demo.crear", "demo.pasos", "demo.actualizar"} <= {x["accion"] for x in repo.auditoria}
    assert cliente.post(f"/mis-vehiculos/{ua}/demos/{d}/eliminar", headers=h["a"]).status_code == 200
    assert d not in repo.demos


def test_la_demo_privada_no_sale_por_ninguna_ruta_ajena(repo, cliente):
    ua, ub, fabrica, h = _escenario(repo, cliente)
    d = cliente.post(f"/mis-vehiculos/{ua}/demos", json={"nombre": "Secreta"}, headers=h["a"]).json()["id_demo"]
    # Rutas públicas y del catálogo técnico: solo fábrica
    assert [x["nombre"] for x in cliente.get(f"/vehiculos/{ua}/demos").json()] == ["Fábrica"]
    assert cliente.get(f"/vehiculos/{ua}/demos/{d}/movimientos").status_code == 404
    assert cliente.post(f"/vehiculos/{ua}/demos/{d}/actualizar", json={"nombre": "x", "activo": True},
                        headers=ADMIN).status_code == 404
    assert cliente.post(f"/vehiculos/{ua}/demos/{d}/eliminar", headers=ADMIN).status_code == 404
    # Otro comprador: ni siquiera puede consultar la unidad ajena
    assert cliente.get(f"/mis-vehiculos/{ua}/demos", headers=h["b"]).status_code == 403
    assert cliente.get(f"/mis-vehiculos/{ua}/demos/{d}", headers=h["b"]).status_code == 403
    assert cliente.post(f"/mis-vehiculos/{ua}/demos", json={"nombre": "Intrusa"}, headers=h["b"]).status_code == 403
    # El admin (aun con token) tampoco la toca desde su editor de fábrica
    assert cliente.post(f"/admin/unidades/{ua}/demos/{d}/pasos", json={"pasos": []},
                        headers=h["jefa"]).status_code in (403, 404)


def test_limites_del_modelo_al_guardar(repo, cliente):
    ua, ub, fabrica, h = _escenario(repo, cliente)
    d = cliente.post(f"/mis-vehiculos/{ua}/demos", json={"nombre": "Larga"}, headers=h["a"]).json()["id_demo"]
    url = f"/mis-vehiculos/{ua}/demos/{d}/pasos"
    casos = [
        [{"id_comando": 101, "duracion_ms": 5001}],                                    # paso > 5000
        [{"id_comando": 101, "duracion_ms": 1000, "pausa_ms": 6000}],                  # pausa > 5000
        [{"id_comando": 101, "duracion_ms": 1000}] * 4,                                # > 3 pasos
        [{"id_comando": 101, "duracion_ms": 5000}, {"id_comando": 102, "duracion_ms": 4500}],   # total > 9000
        [{"id_comando": 999, "duracion_ms": 1000}],                                    # comando ajeno
    ]
    for pasos in casos:
        r = cliente.post(url, json={"pasos": pasos}, headers=h["a"])
        assert r.status_code == 400, (pasos, r.text)
    assert repo.pasos[d] == []                                                         # nada se guardó
    assert cliente.get(f"/vehiculos/{ua}/limites").json()["max_paso_ms"] == 5000


def test_fabrica_solo_la_edita_la_empresa(repo, cliente):
    ua, ub, fabrica, h = _escenario(repo, cliente)
    assert cliente.post(f"/mis-vehiculos/{ua}/demos/{fabrica}/pasos", json={"pasos": []}, headers=h["a"]).status_code == 403
    assert cliente.post(f"/mis-vehiculos/{ua}/demos/{fabrica}/eliminar", headers=h["a"]).status_code == 403
    r = cliente.post(f"/admin/unidades/{ua}/demos/{fabrica}/pasos",
                     json={"pasos": [{"id_comando": 102, "duracion_ms": 2000}, {"id_comando": 101, "duracion_ms": 1000}]},
                     headers=h["jefa"])
    assert r.status_code == 200 and [m["comando"] for m in r.json()["movimientos"]] == ["RETROCEDER", "AVANZAR"]
    # Las rutas técnicas antiguas también respetan los límites ahora (H9)
    r = cliente.post(f"/vehiculos/{ua}/demos/{fabrica}/movimientos",
                     json={"id_comando": 101, "orden": 9, "duracion_ms": 600000, "pausa_ms": 0}, headers=ADMIN)
    assert r.status_code == 400


def test_iniciar_demo_privada_solo_su_dueno(repo, cliente):
    ua, ub, fabrica, h = _escenario(repo, cliente)
    d = cliente.post(f"/mis-vehiculos/{ua}/demos", json={"nombre": "Mía"}, headers=h["a"]).json()["id_demo"]
    cliente.post(f"/mis-vehiculos/{ua}/demos/{d}/pasos", json={"pasos": [{"id_comando": 101, "duracion_ms": 300}]}, headers=h["a"])
    assert cliente.post(f"/vehiculos/{ua}/demos/{d}/iniciar", headers=OPERADOR).status_code == 404   # clave: no la ve
    assert cliente.post(f"/vehiculos/{ua}/demos/{d}/iniciar", headers=h["b"]).status_code == 403     # unidad ajena
    r = cliente.post(f"/vehiculos/{ua}/demos/{d}/iniciar", headers=h["a"])
    assert r.status_code == 202, r.text
    time.sleep(0.6)


def test_demo_fuera_de_limites_no_se_inicia(repo, cliente):
    ua, ub, fabrica, h = _escenario(repo, cliente)
    larga = repo.crear_demo(ua, "Antigua", None)
    repo.guardar_pasos_demo(larga, '[{"id_comando": 101, "duracion_ms": 20000, "pausa_ms": 0}]')   # creada antes de V011
    r = cliente.post(f"/vehiculos/{ua}/demos/{larga}/iniciar", headers=OPERADOR)
    assert r.status_code == 409 and "límites" in r.json()["detail"]


def test_detener_tiene_prioridad_durante_una_demo(repo, cliente):
    ua, ub, fabrica, h = _escenario(repo, cliente)
    repo.guardar_pasos_demo(fabrica, '[{"id_comando": 101, "duracion_ms": 4000, "pausa_ms": 0}, '
                                     '{"id_comando": 102, "duracion_ms": 4000, "pausa_ms": 0}]')
    assert cliente.post(f"/vehiculos/{ua}/demos/{fabrica}/iniciar", headers=h["a"]).status_code == 202
    time.sleep(0.3)
    assert cliente.get(f"/vehiculos/{ua}/demos/ejecucion").json()["en_ejecucion"] is True
    # Otro movimiento: rechazado mientras corre la DEMO
    assert cliente.post(f"/vehiculos/{ua}/movimientos", json={"codigo": 1}, headers=h["a"]).status_code == 409
    # DETENER: cancela la DEMO y se registra
    r = cliente.post(f"/vehiculos/{ua}/movimientos", json={"codigo": 9}, headers=h["a"])
    assert r.status_code == 201 and r.json()["comando"] == "DETENER"
    assert cliente.get(f"/vehiculos/{ua}/demos/ejecucion").json()["en_ejecucion"] is False


def test_sin_v011_las_rutas_del_editor_dan_503(repo, cliente):
    ua, ub, fabrica, h = _escenario(repo, cliente)
    repo.version = 10
    cliente.app.state.contenedor.esquema._version = None          # fuerza a releer la versión
    assert cliente.get(f"/mis-vehiculos/{ua}/demos", headers=h["a"]).status_code == 503
    assert cliente.get(f"/vehiculos/{ua}/limites").status_code == 503
    assert [x["nombre"] for x in cliente.get(f"/vehiculos/{ua}/demos").json()] == ["Fábrica"]
