"""Etapa 4: sesión, rotación de tokens, bloqueo, códigos y autorización por unidad.

Las reglas de los SP reales se prueban contra MySQL en `migrar probar`
(probar_v010); aquí se prueban la API y los servicios con el repositorio falso.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core import contrasenas
from app.core.config import AuthSettings
from tests.conftest import ADMIN, OPERADOR, SECRETO, RepositorioFalso, construir_cliente

CLAVE = "Contrasena123"


# ------------------------------------------------------------------ utilidades

def _usuario(repo, correo, rol="usuario", contrasena=CLAVE, activo=True):
    i = repo.crear_usuario(correo, correo.split("@")[0], rol)
    repo.usuarios[i].update(hash=contrasenas.hashear(contrasena), activo=activo)
    return i


def _unidad(repo, nombre, estado="inventario", dueno=None):
    if not repo.modelos:
        repo.crear_modelo("Modelo X", None, "ESP32", 3000, 3000, 20, 60000)
    i = repo._nuevo("vehiculo")
    repo.unidades[i] = {"id_vehiculo": i, "nombre": nombre, "numero_serie": None, "estado_comercial": estado,
                        "es_simulada": False, "activo": True, "descripcion": None, "microcontrolador": "ESP32",
                        "fecha_registro": None, "id_modelo": 1}
    repo.vehiculos[i] = {"id_vehiculo": i, "nombre": nombre, "activo": True}
    repo.comandos[i] = [{"id_comando": 500 + i, "id_vehiculo": i, "nombre": "AVANZAR", "codigo": 1,
                         "descripcion": None, "activo": True}]
    if dueno:
        repo.asignar_unidad(i, dueno, None)
    return i


def _login(cliente, correo, contrasena=CLAVE):
    return cliente.post("/auth/login", json={"correo": correo, "contrasena": contrasena})


def _bearer(sesion):
    return {"Authorization": f"Bearer {sesion['token_acceso']}"}


def _mover(cliente, id_vehiculo, cabeceras=None):
    return cliente.post(f"/vehiculos/{id_vehiculo}/movimientos", json={"codigo": 1}, headers=cabeceras or {})


@pytest.fixture
def sesion_de(cliente):
    def _sesion(correo):
        r = _login(cliente, correo)
        assert r.status_code == 200, r.text
        return r.json()
    return _sesion


# ------------------------------------------------------------------ inicio de sesión

def test_login_correcto_y_yo(repo, cliente):
    _usuario(repo, "ana@ejemplo.com")
    r = _login(cliente, "  ANA@ejemplo.com ")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    s = r.json()
    assert s["tipo"] == "Bearer" and s["expira_en"] == 600 and s["usuario"]["rol"] == "usuario"
    assert "hash" not in str(s)
    # En la base solo queda el HMAC del token de renovación, nunca el valor.
    assert s["token_renovacion"] not in repo.tokens and len(next(iter(repo.tokens))) == 64
    yo = cliente.get("/auth/yo", headers=_bearer(s))
    assert yo.status_code == 200 and yo.json()["correo"] == "ana@ejemplo.com"
    assert any(a["accion"] == "login.ok" for a in repo.auditoria)


def test_error_generico_no_revela_si_el_correo_existe(repo, cliente):
    _usuario(repo, "ana@ejemplo.com")
    malo = _login(cliente, "ana@ejemplo.com", "Equivocada999")
    inexistente = _login(cliente, "nadie@ejemplo.com", "Equivocada999")
    assert malo.status_code == inexistente.status_code == 401
    assert malo.json() == inexistente.json()
    assert malo.headers["www-authenticate"] == "Bearer"


def test_usuario_sin_contrasena_o_inactivo_no_entra(repo, cliente):
    i = repo.crear_usuario("nuevo@ejemplo.com", "Nuevo", "usuario")       # aún sin contraseña
    assert _login(cliente, "nuevo@ejemplo.com", "Cualquiera123").status_code == 401
    _usuario(repo, "baja@ejemplo.com", activo=False)
    assert _login(cliente, "baja@ejemplo.com").status_code == 401
    assert repo.usuarios[i].get("fallos") == 1


def test_bloqueo_tras_5_fallos(repo, cliente):
    _usuario(repo, "ana@ejemplo.com")
    for _ in range(5):
        assert _login(cliente, "ana@ejemplo.com", "Equivocada999").status_code == 401
    r = _login(cliente, "ana@ejemplo.com")                    # aun con la contraseña correcta
    assert r.status_code == 429 and "15 minutos" in r.json()["detail"]


def test_limite_de_tasa_por_ip(repo, cliente):
    for n in range(20):
        assert _login(cliente, f"x{n}@ejemplo.com", "Equivocada999").status_code == 401
    assert _login(cliente, "otro@ejemplo.com", "Equivocada999").status_code == 429


def test_token_manipulado_vencido_o_de_otro_secreto(repo, cliente, sesion_de):
    i = _usuario(repo, "ana@ejemplo.com")
    s = sesion_de("ana@ejemplo.com")
    datos = jwt.decode(s["token_acceso"], SECRETO, algorithms=["HS256"], issuer="vehiculos-iot")
    ahora = int(datetime.now(timezone.utc).timestamp())
    casos = {
        "alterado": s["token_acceso"][:-3] + ("aaa" if not s["token_acceso"].endswith("aaa") else "bbb"),
        "otro_secreto": jwt.encode(datos, "otro-secreto-de-al-menos-32-caracteres!!", algorithm="HS256"),
        "vencido": jwt.encode({**datos, "exp": ahora - 5}, SECRETO, algorithm="HS256"),
        "rol_inventado": jwt.encode({**datos, "rol": "superadmin"}, SECRETO, algorithm="HS256"),
        "sin_firma": jwt.encode(datos, None, algorithm="none"),
    }
    for nombre, token in casos.items():
        r = cliente.get("/auth/yo", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, nombre
    # El rol sale de la BASE, no del token: subirse el rol en el JWT no sirve.
    repo.usuarios[i]["rol"] = "usuario"
    falso_admin = jwt.encode({**datos, "rol": "admin"}, SECRETO, algorithm="HS256")
    assert cliente.get("/admin/metricas", headers={"Authorization": f"Bearer {falso_admin}"}).status_code == 403


# ------------------------------------------------------------------ renovación

def test_renovar_rota_y_la_reutilizacion_cierra_la_familia(repo, cliente, sesion_de):
    _usuario(repo, "ana@ejemplo.com")
    s1 = sesion_de("ana@ejemplo.com")
    r = cliente.post("/auth/renovar", json={"token_renovacion": s1["token_renovacion"]})
    assert r.status_code == 200
    s2 = r.json()
    assert s2["token_renovacion"] != s1["token_renovacion"]
    # Alguien reutiliza el token viejo (robado): 401 y se revoca también el nuevo.
    assert cliente.post("/auth/renovar", json={"token_renovacion": s1["token_renovacion"]}).status_code == 401
    assert cliente.post("/auth/renovar", json={"token_renovacion": s2["token_renovacion"]}).status_code == 401
    assert any(a["accion"] == "sesion.reutilizacion" for a in repo.auditoria)


def test_renovar_token_inventado_o_vencido(repo, cliente, sesion_de):
    _usuario(repo, "ana@ejemplo.com")
    s = sesion_de("ana@ejemplo.com")
    assert cliente.post("/auth/renovar", json={"token_renovacion": "x" * 43}).status_code == 401
    for t in repo.tokens.values():
        t["expira"] = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    assert cliente.post("/auth/renovar", json={"token_renovacion": s["token_renovacion"]}).status_code == 401


def test_salir_revoca(repo, cliente, sesion_de):
    _usuario(repo, "ana@ejemplo.com")
    s = sesion_de("ana@ejemplo.com")
    assert cliente.post("/auth/salir", json={"token_renovacion": s["token_renovacion"]}).status_code == 204
    assert cliente.post("/auth/renovar", json={"token_renovacion": s["token_renovacion"]}).status_code == 401


def test_desactivar_tiene_efecto_inmediato(repo, cliente, sesion_de):
    i = _usuario(repo, "ana@ejemplo.com")
    s = sesion_de("ana@ejemplo.com")
    repo.usuarios[i]["activo"] = False
    assert cliente.get("/auth/yo", headers=_bearer(s)).status_code == 401       # JWT aún vigente
    assert cliente.post("/auth/renovar", json={"token_renovacion": s["token_renovacion"]}).status_code == 401


# ------------------------------------------------------------------ contraseñas

def test_codigo_de_restablecimiento_de_un_solo_uso(repo, cliente, sesion_de):
    _usuario(repo, "jefa@empresa.com", rol="admin")
    i = repo.crear_usuario("cliente@ejemplo.com", "Cliente", "usuario")
    admin = sesion_de("jefa@empresa.com")
    r = cliente.post(f"/admin/usuarios/{i}/codigo-restablecimiento", headers=_bearer(admin))
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    codigo = r.json()["codigo"]
    assert len(codigo) == 11 and codigo[5] == "-"
    assert codigo.replace("-", "") not in str(repo.codigos)                   # solo el HMAC
    assert repo.codigos[-1]["creado_por"] == admin["usuario"]["id_usuario"]

    datos = {"correo": "cliente@ejemplo.com", "codigo": "AAAAA-BBBBB", "contrasena_nueva": "NuevaClave2026"}
    assert cliente.post("/auth/restablecer", json=datos).status_code == 400
    ok = cliente.post("/auth/restablecer", json={**datos, "codigo": codigo.lower()})   # sin importar mayúsculas
    assert ok.status_code == 200
    assert _login(cliente, "cliente@ejemplo.com", "NuevaClave2026").status_code == 200
    assert cliente.post("/auth/restablecer", json={**datos, "codigo": codigo}).status_code == 400   # ya usado


def test_codigo_se_agota_y_el_nuevo_invalida_el_anterior(repo, cliente):
    i = repo.crear_usuario("cliente@ejemplo.com", "Cliente", "usuario")
    viejo = cliente.post(f"/admin/usuarios/{i}/codigo-restablecimiento", headers=ADMIN).json()["codigo"]
    nuevo = cliente.post(f"/admin/usuarios/{i}/codigo-restablecimiento", headers=ADMIN).json()["codigo"]
    datos = {"correo": "cliente@ejemplo.com", "contrasena_nueva": "NuevaClave2026"}
    assert cliente.post("/auth/restablecer", json={**datos, "codigo": viejo}).status_code == 400
    for _ in range(4):
        assert cliente.post("/auth/restablecer", json={**datos, "codigo": "ZZZZZ-ZZZZZ"}).status_code == 400
    # 5 intentos fallidos: el código correcto ya no sirve.
    assert cliente.post("/auth/restablecer", json={**datos, "codigo": nuevo}).status_code == 400


def test_politica_de_contrasenas(repo, cliente):
    i = repo.crear_usuario("cliente@ejemplo.com", "Cliente", "usuario")
    codigo = cliente.post(f"/admin/usuarios/{i}/codigo-restablecimiento", headers=ADMIN).json()["codigo"]
    for mala in ("solo-letras-sin-numeros", "1234567890123", "cliente2026x"):
        r = cliente.post("/auth/restablecer", json={"correo": "cliente@ejemplo.com", "codigo": codigo,
                                                    "contrasena_nueva": mala})
        assert r.status_code == 400, mala


def test_cambiar_contrasena_cierra_otras_sesiones(repo, cliente, sesion_de):
    _usuario(repo, "ana@ejemplo.com")
    otra = sesion_de("ana@ejemplo.com")
    s = sesion_de("ana@ejemplo.com")
    cuerpo = {"contrasena_actual": "Mala0000000", "contrasena_nueva": "OtraClave2026"}
    assert cliente.post("/auth/cambiar-contrasena", json=cuerpo, headers=_bearer(s)).status_code == 400
    r = cliente.post("/auth/cambiar-contrasena", json={**cuerpo, "contrasena_actual": CLAVE}, headers=_bearer(s))
    assert r.status_code == 200 and r.json()["token_renovacion"]
    assert cliente.post("/auth/renovar", json={"token_renovacion": otra["token_renovacion"]}).status_code == 401
    assert _login(cliente, "ana@ejemplo.com", "OtraClave2026").status_code == 200


# ------------------------------------------------------------------ autorización por unidad (BOLA)

def test_comprador_solo_opera_y_ve_sus_unidades(repo, cliente, sesion_de):
    a, b = _usuario(repo, "a@ejemplo.com"), _usuario(repo, "b@ejemplo.com")
    ua, ub = _unidad(repo, "Unidad A", dueno=a), _unidad(repo, "Unidad B", dueno=b)
    sa = sesion_de("a@ejemplo.com")
    assert _mover(cliente, ua, _bearer(sa)).status_code == 201
    assert repo.historial_autor == [(ua, 500 + ua, a)]                         # el historial guarda el autor
    assert _mover(cliente, ub, _bearer(sa)).status_code == 403                 # BOLA: unidad ajena
    assert cliente.post(f"/vehiculos/{ub}/demos/cancelar", headers=_bearer(sa)).status_code == 403
    mias = cliente.get("/mis-vehiculos", headers=_bearer(sa)).json()
    assert [v["id_vehiculo"] for v in mias] == [ua]
    assert cliente.get(f"/mis-vehiculos/{ub}/soporte", headers=_bearer(sa)).status_code == 403
    assert cliente.post(f"/mis-vehiculos/{ub}/soporte", json={"horas": 2},
                        headers=_bearer(sa)).status_code == 403
    assert cliente.get("/admin/metricas", headers=_bearer(sa)).status_code == 403   # no es admin
    assert _mover(cliente, 999, _bearer(sa)).status_code == 404


def test_admin_necesita_soporte_para_una_unidad_vendida(repo, cliente, sesion_de):
    _usuario(repo, "jefa@empresa.com", rol="admin")
    c = _usuario(repo, "cliente@ejemplo.com")
    vendida = _unidad(repo, "Vendida", dueno=c)
    inventario = _unidad(repo, "En bodega")
    sad, sc = sesion_de("jefa@empresa.com"), sesion_de("cliente@ejemplo.com")

    assert _mover(cliente, inventario, _bearer(sad)).status_code == 201
    assert _mover(cliente, vendida, _bearer(sad)).status_code == 403
    r = cliente.post(f"/mis-vehiculos/{vendida}/soporte", json={"horas": 2, "motivo": "Revisión"},
                     headers=_bearer(sc))
    assert r.status_code == 201 and r.json()["vigente"] is True
    assert _mover(cliente, vendida, _bearer(sad)).status_code == 201
    assert cliente.post(f"/mis-vehiculos/{vendida}/soporte/revocar",
                        headers=_bearer(sc)).json()["revocadas"] == 1
    assert _mover(cliente, vendida, _bearer(sad)).status_code == 403
    assert {"soporte.otorgar", "soporte.revocar"} <= {a["accion"] for a in repo.auditoria}


def test_soporte_para_un_admin_concreto(repo, cliente, sesion_de):
    uno = _usuario(repo, "uno@empresa.com", rol="admin")
    _usuario(repo, "dos@empresa.com", rol="admin")
    c = _usuario(repo, "cliente@ejemplo.com")
    vendida = _unidad(repo, "Vendida", dueno=c)
    cliente.post(f"/mis-vehiculos/{vendida}/soporte", json={"horas": 1, "id_administrador": uno},
                 headers=_bearer(sesion_de("cliente@ejemplo.com")))
    assert _mover(cliente, vendida, _bearer(sesion_de("uno@empresa.com"))).status_code == 201
    assert _mover(cliente, vendida, _bearer(sesion_de("dos@empresa.com"))).status_code == 403


def test_admin_con_token_queda_en_la_auditoria(repo, cliente, sesion_de):
    yo = _usuario(repo, "jefa@empresa.com", rol="admin")
    r = cliente.post("/admin/usuarios", json={"correo": "nuevo@ejemplo.com", "nombre": "Nuevo", "rol": "usuario"},
                     headers=_bearer(sesion_de("jefa@empresa.com")))
    assert r.status_code == 201
    alta = next(a for a in repo.auditoria if a["accion"] == "usuario.crear")
    assert alta["id_usuario"] == yo and alta["rol_actor"] == "admin"


# ------------------------------------------------------------------ transición y configuración

def test_la_clave_x_api_key_sigue_funcionando(repo, cliente):
    u = _unidad(repo, "Unidad", dueno=_usuario(repo, "a@ejemplo.com"))
    assert _mover(cliente, u, OPERADOR).status_code == 201
    assert _mover(cliente, u).status_code == 401                               # sin nada y sin CONTROL_ABIERTO
    assert _mover(cliente, u, {"X-API-Key": "clave-que-no-existe"}).status_code == 401
    assert repo.historial_autor == []                                          # sin usuario: SP original


def test_control_abierto_sigue_aceptando_sin_clave(repo):
    with construir_cliente(repo, control_abierto=True) as c:
        assert _mover(c, 1).status_code == 201


def test_lectura_cerrada_exige_dueno(repo):
    auth = AuthSettings(secreto=SECRETO, lectura_abierta=False)
    a = _usuario(repo, "a@ejemplo.com")
    _usuario(repo, "b@ejemplo.com")
    u = _unidad(repo, "Unidad A", dueno=a)
    with construir_cliente(repo, auth=auth) as c:
        assert c.get(f"/vehiculos/{u}/historial").status_code == 401
        sa = c.post("/auth/login", json={"correo": "a@ejemplo.com", "contrasena": CLAVE}).json()
        sb = c.post("/auth/login", json={"correo": "b@ejemplo.com", "contrasena": CLAVE}).json()
        assert c.get(f"/vehiculos/{u}/historial", headers=_bearer(sa)).status_code == 200
        assert c.get(f"/vehiculos/{u}/historial", headers=_bearer(sb)).status_code == 403
        assert c.get(f"/vehiculos/{u}/comandos", headers=_bearer(sb)).status_code == 403
        assert c.get(f"/vehiculos/{u}/historial", headers=OPERADOR).status_code == 200


def test_lectura_abierta_por_defecto(repo, cliente):
    assert cliente.get("/vehiculos/1/historial").status_code == 200


def test_sin_token_secreto_la_sesion_da_503_y_lo_demas_sigue(repo):
    _usuario(repo, "ana@ejemplo.com")
    with construir_cliente(repo, auth=AuthSettings(secreto="")) as c:
        assert _login(c, "ana@ejemplo.com").status_code == 503
        assert c.get("/vehiculos/1/historial").status_code == 200
        assert c.get("/admin/metricas", headers=ADMIN).status_code == 200


def test_sin_v010_la_sesion_da_503(repo):
    repo.version = 9
    _usuario(repo, "ana@ejemplo.com")
    with construir_cliente(repo) as c:
        assert _login(c, "ana@ejemplo.com").status_code == 503
        assert c.get("/admin/metricas", headers=ADMIN).status_code == 200
        assert _mover(c, 1, OPERADOR).status_code == 201


def test_cors_permite_authorization(cliente):
    r = cliente.options("/auth/yo", headers={"Origin": "https://juanarmando30.github.io",
                                              "Access-Control-Request-Method": "GET",
                                              "Access-Control-Request-Headers": "authorization"})
    assert r.status_code == 200 and "authorization" in r.headers["access-control-allow-headers"].lower()


def test_secreto_corto_o_igual_a_una_clave_se_rechaza(monkeypatch):
    monkeypatch.setenv("TOKEN_SECRETO", "corto")
    with pytest.raises(ValueError):
        AuthSettings.from_env()
    monkeypatch.setenv("TOKEN_SECRETO", "x" * 40)
    monkeypatch.setenv("API_KEY_ADMIN", "x" * 40)
    with pytest.raises(ValueError):
        AuthSettings.from_env()


def test_repositorio_falso_v010():
    assert RepositorioFalso().version == 13


# ------------------------------------------------------------------ Etapa 5: catálogo técnico con sesión

def test_admin_con_sesion_edita_el_catalogo_tecnico_sin_clave(repo, cliente, sesion_de):
    _usuario(repo, "jefa@empresa.com", rol="admin")
    _usuario(repo, "cliente@ejemplo.com")
    r = cliente.post("/vehiculos/1/eliminar", headers=_bearer(sesion_de("jefa@empresa.com")))
    assert r.status_code in (200, 204, 409), r.text          # pasó la autorización (409 = tiene historial)
    assert cliente.post("/vehiculos/1/eliminar",
                        headers=_bearer(sesion_de("cliente@ejemplo.com"))).status_code == 403
    assert cliente.post("/vehiculos/1/eliminar").status_code == 401
