"""Pruebas de los procedimientos nuevos, por versión de migración.

`python -m app.db.migrar probar` las ejecuta SOLO en la copia de prueba,
después de aplicar la versión y otra vez al reaplicar. Cada prueba crea
datos marcados como de prueba, comprueba reglas de negocio (también las que
deben FALLAR) y borra todo lo que creó: las tablas originales deben quedar
con el mismo número de registros.
"""

import hashlib
import json

import mysql.connector

ERRNO_SIGNAL = 1644          # SIGNAL SQLSTATE '45000' (regla de negocio)
ERRNO_FK_PADRE = 1451        # no se puede borrar: registro en uso


class FallaPrueba(Exception):
    pass


def _afirmar(condicion, mensaje):
    if not condicion:
        raise FallaPrueba(mensaje)


def _espera(ex, minutos):
    """Último parámetro de sp_invitado_reservar: minutos hasta V016, SEGUNDOS desde V017."""
    return minutos * 60 if ex.llamar("sp_version_esquema")[0]["version"] >= 17 else minutos


def _debe_fallar(funcion, errno, descripcion):
    try:
        funcion()
    except mysql.connector.Error as error:
        _afirmar(error.errno == errno, f"{descripcion}: se esperaba el error {errno} y llegó {error.errno} ({error.msg})")
        return error.msg
    raise FallaPrueba(f"{descripcion}: debía fallar y no falló")


def probar_v009(ex, base):
    ex.usar(base)
    antes = ex.conteos(base)
    _afirmar(ex.llamar("sp_version_esquema")[0]["version"] >= 9, "sp_version_esquema debe ser 9 o más")

    # ---- Modelo y capacidades
    m = int(ex.llamar("sp_crear_modelo", ("Modelo de prueba V009", "prueba", "ESP32", 3000, 5000, 20, 60000))[0]["id_modelo"])
    ex.llamar("sp_guardar_capacidad", (m, "AVANZAR", 1, None, "movimiento", 1))
    ex.llamar("sp_guardar_capacidad", (m, "DETENER", 9, None, "paro", 1))
    ex.llamar("sp_guardar_capacidad", (m, "LUZ", 10, None, "accesorio", 0))
    ex.llamar("sp_guardar_capacidad", (m, "AVANZAR", 1, "editada", "movimiento", 0))      # actualiza, no duplica
    capacidades = ex.llamar("sp_listar_capacidades", (m,))
    _afirmar([c["codigo"] for c in capacidades] == [1, 9, 10], f"capacidades inesperadas: {capacidades}")
    _afirmar(capacidades[0]["descripcion"] == "editada", "sp_guardar_capacidad no actualizó")
    ex.llamar("sp_eliminar_capacidad", (m, 10))
    _afirmar(len(ex.llamar("sp_listar_capacidades", (m,))) == 2, "sp_eliminar_capacidad no borró")
    ex.llamar("sp_actualizar_modelo", (m, "Modelo de prueba V009", "editado", "ESP32", 3000, 6000, 20, 60000, 1))
    modelo = ex.llamar("sp_obtener_modelo", (m,))[0]
    _afirmar(modelo["max_paso_ms"] == 6000 and modelo["capacidades"] == 2, f"sp_obtener_modelo: {modelo}")
    _afirmar(any(x["id_modelo"] == m for x in ex.llamar("sp_listar_modelos")), "sp_listar_modelos no lo incluye")
    _debe_fallar(lambda: ex.llamar("sp_actualizar_modelo", (m, "Modelo de prueba V009", "", "ESP32", 3000, 70000, 20, 60000, 1)),
                 3819, "límites incoherentes (max_demo_ms < max_paso_ms) deben violar el CHECK")

    # ---- Unidad: nace con el catálogo del modelo
    _debe_fallar(lambda: ex.llamar("sp_crear_unidad", (m, "x", None, None, "vendida", 0)),
                 ERRNO_SIGNAL, "una unidad nueva no puede nacer vendida")
    u = int(ex.llamar("sp_crear_unidad", (m, "Unidad de prueba V009", "SERIE-PRUEBA-V009", None, "inventario", 1))[0]["id_vehiculo"])
    unidad = ex.llamar("sp_obtener_unidad", (u,))[0]
    _afirmar(unidad["estado_comercial"] == "inventario" and unidad["modelo"] == "Modelo de prueba V009"
             and unidad["es_simulada"] == 1 and unidad["id_propietario"] is None, f"sp_obtener_unidad: {unidad}")
    catalogo = {c["codigo"]: c["id_comando"] for c in ex.llamar("sp_obtener_comandos_vehiculo", (u,))}
    _afirmar(set(catalogo) == {1, 9}, f"el catálogo de la unidad no copia las capacidades: {catalogo}")
    lista = ex.llamar("sp_listar_unidades", (None, m, "PRUEBA-V009", 10, 0))
    _afirmar(len(lista) == 1 and lista[0]["total"] == 1, f"sp_listar_unidades con filtros: {lista}")
    _debe_fallar(lambda: ex.llamar("sp_actualizar_unidad", (u, "x", "SERIE-PRUEBA-V009", None, "vendida", 1)),
                 ERRNO_SIGNAL, "el estado vendida no se pone a mano")
    ex.llamar("sp_actualizar_unidad", (u, "Unidad de prueba V009 (editada)", "SERIE-PRUEBA-V009", "x", "exhibicion", 1))

    # ---- Usuarios
    cliente = int(ex.llamar("sp_crear_usuario", ("cliente.v009@prueba.local", "Cliente de prueba", "usuario"))[0]["id_usuario"])
    admin = int(ex.llamar("sp_crear_usuario", ("admin.v009@prueba.local", "Admin de prueba", "admin"))[0]["id_usuario"])
    _debe_fallar(lambda: ex.llamar("sp_crear_usuario", ("CLIENTE.V009@prueba.local", "Repetido", "usuario")),
                 1062, "el correo es único sin importar mayúsculas")
    ex.llamar("sp_actualizar_usuario", (cliente, "Cliente de prueba (editado)", "usuario", 1))
    _afirmar(ex.llamar("sp_obtener_usuario", (cliente,))[0]["tiene_contrasena"] == 0, "un usuario nuevo no tiene contraseña")
    _afirmar(any(x["id_usuario"] == cliente for x in ex.llamar("sp_listar_usuarios", ("usuario", 1, "v009", 10, 0))),
             "sp_listar_usuarios con filtros")
    admins_activos = ex.valor("SELECT COUNT(*) FROM usuarios WHERE rol = 'admin' AND activo = 1")
    if admins_activos == 1:                       # en la copia no hay otros administradores
        _debe_fallar(lambda: ex.llamar("sp_actualizar_usuario", (admin, "Admin de prueba", "usuario", 1)),
                     ERRNO_SIGNAL, "no se puede quitar el último administrador")

    # ---- Asignación: solo a clientes activos; marca la unidad vendida
    _debe_fallar(lambda: ex.llamar("sp_asignar_unidad", (u, admin, admin)), ERRNO_SIGNAL, "no se asigna a un administrador")
    a1 = int(ex.llamar("sp_asignar_unidad", (u, cliente, admin))[0]["id_asignacion"])
    _afirmar(ex.llamar("sp_obtener_unidad", (u,))[0]["estado_comercial"] == "vendida", "asignar no marca vendida")
    _debe_fallar(lambda: ex.llamar("sp_asignar_unidad", (u, cliente, None)), ERRNO_SIGNAL, "no se repite la misma asignación")
    _afirmar([x["id_vehiculo"] for x in ex.llamar("sp_mis_vehiculos", (cliente,))] == [u], "sp_mis_vehiculos")
    _afirmar(ex.llamar("sp_mis_vehiculos", (admin,)) == [], "sp_mis_vehiculos de otro usuario debe estar vacío")
    _debe_fallar(lambda: ex.llamar("sp_actualizar_usuario", (cliente, "x", "admin", 1)),
                 ERRNO_SIGNAL, "un cliente con unidades no cambia de rol")
    _debe_fallar(lambda: ex.llamar("sp_baja_unidad", (u,)), ERRNO_SIGNAL, "no se da de baja una unidad con comprador")
    _debe_fallar(lambda: ex.llamar("sp_eliminar_vehiculo", (u,)), ERRNO_FK_PADRE,
                 "una unidad con historia comercial no se puede borrar (H13)")
    asignaciones = ex.llamar("sp_listar_asignaciones", (u, None, 1, 10, 0))
    _afirmar(len(asignaciones) == 1 and asignaciones[0]["vigente"] == 1, f"sp_listar_asignaciones: {asignaciones}")
    _debe_fallar(lambda: ex.llamar("sp_finalizar_asignacion", (a1, "x", "vendida")), ERRNO_SIGNAL, "estado resultante inválido")
    ex.llamar("sp_finalizar_asignacion", (a1, "prueba", "inventario"))
    _afirmar(ex.llamar("sp_obtener_unidad", (u,))[0]["estado_comercial"] == "inventario", "finalizar no deja inventario")
    _afirmar(ex.llamar("sp_mis_vehiculos", (cliente,)) == [], "tras finalizar el cliente ya no ve la unidad")
    _debe_fallar(lambda: ex.llamar("sp_finalizar_asignacion", (a1, "x", "inventario")), ERRNO_SIGNAL, "no se finaliza dos veces")

    # ---- Historial reciente (LIMIT) y auditoría
    for _ in range(3):
        ex.llamar("sp_registrar_historial", (u, catalogo[1], "PRUEBA_V009"))
    _afirmar(len(ex.llamar("sp_obtener_historial_reciente", (u, 2))) == 2, "sp_obtener_historial_reciente no aplica LIMIT")
    ex.llamar("sp_registrar_auditoria", (admin, "admin", "prueba.v009", "unidad", str(u), "ok", json.dumps({"paso": 1}), None))
    auditoria = ex.llamar("sp_listar_auditoria", ("prueba.v009", None, None, None, None, None, 10, 0))
    _afirmar(len(auditoria) == 1 and auditoria[0]["usuario"] == "Admin de prueba", f"sp_listar_auditoria: {auditoria}")
    _debe_fallar(lambda: ex.llamar("sp_registrar_auditoria", (None, "intruso", "x", None, None, "ok", None, None)),
                 3819, "rol_actor fuera de la lista debe violar el CHECK")
    metricas = ex.llamar("sp_metricas_admin")[0]
    _afirmar(metricas["unidades"] >= 2 and metricas["unidades_simuladas"] >= 1, f"sp_metricas_admin: {metricas}")

    # ---- Baja (sin comprador) y limpieza
    ex.llamar("sp_baja_unidad", (u,))
    unidad = ex.llamar("sp_obtener_unidad", (u,))[0]
    _afirmar(unidad["estado_comercial"] == "baja" and unidad["activo"] == 0, "sp_baja_unidad")

    ex.ejecutar("DELETE FROM auditoria WHERE accion LIKE 'prueba.v009%'")
    ex.ejecutar("DELETE FROM asignaciones WHERE id_vehiculo = %s", (u,))
    ex.llamar("sp_eliminar_vehiculo", (u,))                 # en cascada: comandos, historial de prueba
    ex.ejecutar("DELETE FROM modelo_comandos WHERE id_modelo = %s", (m,))
    ex.ejecutar("DELETE FROM modelos_vehiculo WHERE id_modelo = %s", (m,))
    ex.ejecutar("DELETE FROM usuarios WHERE id_usuario IN (%s, %s)", (cliente, admin))
    despues = ex.conteos(base)
    _afirmar(antes == despues, f"la prueba dejó registros en las tablas originales: {antes} → {despues}")


def _h(texto):
    return hashlib.sha256(texto.encode()).hexdigest()


def probar_v010(ex, base):
    ex.usar(base)
    antes = ex.conteos(base)
    _afirmar(ex.llamar("sp_version_esquema")[0]["version"] >= 10, "sp_version_esquema debe ser 10 o más")
    futuro = ex.valor("SELECT UTC_TIMESTAMP() + INTERVAL 1 DAY")
    pasado_seguro = ex.valor("SELECT UTC_TIMESTAMP() + INTERVAL 2 SECOND")

    u = int(ex.llamar("sp_crear_usuario", ("login.v010@prueba.local", "Login de prueba", "usuario"))[0]["id_usuario"])
    a = int(ex.llamar("sp_crear_usuario", ("admin.v010@prueba.local", "Admin V010", "admin"))[0]["id_usuario"])

    # ---- Login: hash visible solo para la API; bloqueo tras N fallos
    fila = ex.llamar("sp_login_obtener", ("login.v010@prueba.local",))[0]
    _afirmar(fila["hash_contrasena"] is None and fila["bloqueado"] == 0, f"sp_login_obtener: {fila}")
    _afirmar(ex.llamar("sp_login_obtener", ("nadie@prueba.local",)) == [], "un correo inexistente no devuelve filas")
    for _ in range(3):
        ex.llamar("sp_login_resultado", (u, 0, 3, 15))
    fila = ex.llamar("sp_login_obtener", ("login.v010@prueba.local",))[0]
    _afirmar(fila["bloqueado"] == 1 and fila["intentos_fallidos"] == 0, f"3 fallos deben bloquear: {fila}")
    ex.llamar("sp_login_resultado", (u, 1, 3, 15))
    fila = ex.llamar("sp_login_obtener", ("login.v010@prueba.local",))[0]
    _afirmar(fila["bloqueado"] == 0, "un acceso correcto desbloquea")
    ex.llamar("sp_cambiar_contrasena", (u, "$argon2id$v=19$prueba"))
    _afirmar(ex.llamar("sp_login_obtener", ("login.v010@prueba.local",))[0]["hash_contrasena"] == "$argon2id$v=19$prueba",
             "sp_cambiar_contrasena")
    _afirmar(ex.llamar("sp_obtener_usuario_auth", (u,))[0]["rol"] == "usuario", "sp_obtener_usuario_auth")

    # ---- Tokens: rotación y detección de reutilización
    ex.llamar("sp_token_crear", (u, _h("t1"), "f" * 32, futuro, "prueba"))
    r = ex.llamar("sp_token_usar", (_h("t1"), _h("t2"), futuro, "prueba"))[0]
    _afirmar(r["resultado"] == "ok" and r["id_usuario"] == u and r["rol"] == "usuario", f"rotación: {r}")
    r = ex.llamar("sp_token_usar", (_h("t2"), _h("t3"), futuro, "prueba"))[0]
    _afirmar(r["resultado"] == "ok", "el reemplazo sirve una vez")
    r = ex.llamar("sp_token_usar", (_h("t1"), _h("t4"), futuro, "prueba"))[0]
    _afirmar(r["resultado"] == "reutilizado" and r["id_usuario"] is None, f"reutilizar t1 debe detectarse: {r}")
    r = ex.llamar("sp_token_usar", (_h("t3"), _h("t5"), futuro, "prueba"))[0]
    _afirmar(r["resultado"] == "revocado", "tras la reutilización toda la familia queda revocada (t3 también)")
    _afirmar(ex.llamar("sp_token_usar", (_h("nunca"), _h("x"), futuro, "prueba"))[0]["resultado"] == "invalido",
             "token desconocido")
    ex.llamar("sp_token_crear", (u, _h("s1"), "g" * 32, futuro, "prueba"))
    ex.llamar("sp_token_revocar", (_h("s1"),))
    _afirmar(ex.llamar("sp_token_usar", (_h("s1"), _h("s2"), futuro, "prueba"))[0]["resultado"] == "revocado",
             "cerrar sesión revoca")
    ex.llamar("sp_token_crear", (u, _h("e1"), "h" * 32, pasado_seguro, "prueba"))
    ex.ejecutar("UPDATE tokens_renovacion SET expira_en = UTC_TIMESTAMP(), emitido_en = UTC_TIMESTAMP() - INTERVAL 1 MINUTE "
                "WHERE hash_token = %s", (_h("e1"),))
    _afirmar(ex.llamar("sp_token_usar", (_h("e1"), _h("e2"), futuro, "prueba"))[0]["resultado"] == "expirado",
             "token expirado")
    ex.llamar("sp_token_crear", (u, _h("i1"), "i" * 32, futuro, "prueba"))
    ex.llamar("sp_actualizar_usuario", (u, "Login de prueba", "usuario", 0))            # desactivar revoca
    _afirmar(ex.llamar("sp_token_usar", (_h("i1"), _h("i2"), futuro, "prueba"))[0]["resultado"] == "revocado",
             "desactivar al usuario revoca sus sesiones")
    ex.llamar("sp_actualizar_usuario", (u, "Login de prueba", "usuario", 1))

    # ---- Código de restablecimiento: un solo uso, límite de intentos, el nuevo invalida al anterior
    ex.llamar("sp_codigo_crear", (u, _h("c1"), a, futuro))
    ex.llamar("sp_codigo_crear", (u, _h("c2"), None, futuro))                          # invalida c1
    r = ex.llamar("sp_codigo_usar", ("login.v010@prueba.local", _h("c1"), "$argon2id$nueva", 3))[0]
    _afirmar(r["resultado"] == "invalido", "el código anterior queda invalidado")
    r = ex.llamar("sp_codigo_usar", ("login.v010@prueba.local", _h("c2"), "$argon2id$nueva", 3))[0]
    _afirmar(r["resultado"] == "ok" and r["id_usuario"] == u, f"código válido: {r}")
    _afirmar(ex.llamar("sp_codigo_usar", ("login.v010@prueba.local", _h("c2"), "$argon2id$otra", 3))[0]["resultado"]
             == "invalido", "un código usado no sirve otra vez")
    ex.llamar("sp_codigo_crear", (u, _h("c3"), a, futuro))
    for esperado in ("invalido", "invalido", "agotado"):
        r = ex.llamar("sp_codigo_usar", ("login.v010@prueba.local", _h("mal"), "$x", 3))[0]
        _afirmar(r["resultado"] == esperado, f"intentos fallidos: se esperaba {esperado}, llegó {r}")
    _afirmar(ex.llamar("sp_codigo_usar", ("login.v010@prueba.local", _h("c3"), "$x", 3))[0]["resultado"] == "invalido",
             "un código agotado ya no sirve aunque sea el correcto")

    # ---- Acceso por unidad e historial con autor
    m = int(ex.llamar("sp_crear_modelo", ("Modelo V010", None, "ESP32", 3000, 5000, 20, 60000))[0]["id_modelo"])
    ex.llamar("sp_guardar_capacidad", (m, "AVANZAR", 1, None, "movimiento", 1))
    v = int(ex.llamar("sp_crear_unidad", (m, "Unidad V010", None, None, "inventario", 1))[0]["id_vehiculo"])
    acceso = ex.llamar("sp_acceso_unidad", (u, v))[0]
    _afirmar(acceso["es_propietario"] == 0 and acceso["soporte_vigente"] == 0, f"sin relación: {acceso}")
    ex.llamar("sp_asignar_unidad", (v, u, a))
    acceso = ex.llamar("sp_acceso_unidad", (u, v))[0]
    _afirmar(acceso["es_propietario"] == 1 and acceso["estado_comercial"] == "vendida", f"propietario: {acceso}")
    _afirmar(ex.llamar("sp_acceso_unidad", (a, v))[0]["soporte_vigente"] == 0, "sin soporte otorgado")
    _debe_fallar(lambda: ex.llamar("sp_soporte_otorgar", (v, a, None, "x", futuro)), ERRNO_SIGNAL,
                 "solo el comprador autoriza el soporte")
    _debe_fallar(lambda: ex.llamar("sp_soporte_otorgar", (v, u, u, "x", futuro)), ERRNO_SIGNAL,
                 "el soporte solo se otorga a un administrador")
    ex.llamar("sp_soporte_otorgar", (v, u, a, "prueba", futuro))
    _afirmar(ex.llamar("sp_acceso_unidad", (a, v))[0]["soporte_vigente"] == 1, "soporte vigente para ese admin")
    _afirmar(ex.llamar("sp_soporte_listar", (v,))[0]["vigente"] == 1, "sp_soporte_listar")
    _afirmar(ex.llamar("sp_soporte_revocar", (v, u))[0]["revocadas"] == 1, "sp_soporte_revocar")
    _afirmar(ex.llamar("sp_acceso_unidad", (a, v))[0]["soporte_vigente"] == 0, "tras revocar ya no hay soporte")
    _afirmar(ex.llamar("sp_acceso_unidad", (u, 999999)) == [], "unidad inexistente")
    comando = ex.valor("SELECT id_comando FROM comandos WHERE id_vehiculo = %s AND codigo = 1", (v,))
    ex.llamar("sp_registrar_historial_autor", (v, comando, "PRUEBA_V010", u, None))
    _afirmar(ex.valor("SELECT id_usuario FROM historial_comandos WHERE id_vehiculo = %s", (v,)) == u,
             "el historial guarda el autor")

    # ---- Limpieza
    ex.ejecutar("DELETE FROM autorizaciones_soporte WHERE id_vehiculo = %s", (v,))
    ex.ejecutar("DELETE FROM asignaciones WHERE id_vehiculo = %s", (v,))
    ex.llamar("sp_eliminar_vehiculo", (v,))
    ex.ejecutar("DELETE FROM modelo_comandos WHERE id_modelo = %s", (m,))
    ex.ejecutar("DELETE FROM modelos_vehiculo WHERE id_modelo = %s", (m,))
    ex.ejecutar("DELETE FROM codigos_restablecimiento WHERE id_usuario IN (%s, %s)", (u, a))
    ex.ejecutar("DELETE FROM tokens_renovacion WHERE id_usuario IN (%s, %s)", (u, a))
    ex.ejecutar("DELETE FROM auditoria WHERE id_usuario IN (%s, %s)", (u, a))
    ex.ejecutar("DELETE FROM usuarios WHERE id_usuario IN (%s, %s)", (u, a))
    despues = ex.conteos(base)
    _afirmar(antes == despues, f"la prueba dejó registros en las tablas originales: {antes} → {despues}")


def _diagnostico_demos_existentes(ex):
    """Solo lectura: ¿las DEMO que ya existen cumplen los límites de su modelo?
    Si no, la API (V011) se negará a iniciarlas hasta corregir sus pasos."""
    filas = ex.ejecutar("""
        SELECT d.id_demo, d.nombre, COUNT(dm.id_demo_movimiento),
               COALESCE(MAX(GREATEST(dm.duracion_ms, dm.pausa_ms)), 0),
               COALESCE(SUM(dm.duracion_ms + dm.pausa_ms), 0),
               COALESCE(m.max_paso_ms, 10000), COALESCE(m.max_pasos_demo, 50), COALESCE(m.max_demo_ms, 300000)
          FROM demos d
          JOIN vehiculos v ON v.id_vehiculo = d.id_vehiculo
          LEFT JOIN modelos_vehiculo m ON m.id_modelo = v.id_modelo
          LEFT JOIN demo_movimientos dm ON dm.id_demo = d.id_demo
         GROUP BY d.id_demo, d.nombre, m.max_paso_ms, m.max_pasos_demo, m.max_demo_ms""")
    fuera = [f"«{nombre}» (#{i}: {n} pasos, paso máx. {paso} ms, total {total} ms; límites {mp} ms / {mn} pasos / {md} ms)"
             for i, nombre, n, paso, total, mp, mn, md in filas if n > mn or paso > mp or total > md]
    if fuera:
        ex.log("   ⚠ DEMO existentes FUERA de los límites de su modelo (no se podrán iniciar hasta ajustarlas): "
               + "; ".join(fuera))
    else:
        ex.log(f"   · las {len(filas)} DEMO existentes cumplen los límites de su modelo")


def probar_v011(ex, base):
    ex.usar(base)
    antes = ex.conteos(base)
    _afirmar(ex.llamar("sp_version_esquema")[0]["version"] >= 11, "sp_version_esquema debe ser 11 o más")
    _diagnostico_demos_existentes(ex)

    u = int(ex.llamar("sp_crear_usuario", ("demo.v011@prueba.local", "Comprador V011", "usuario"))[0]["id_usuario"])
    otro = int(ex.llamar("sp_crear_usuario", ("otro.v011@prueba.local", "Otro V011", "usuario"))[0]["id_usuario"])
    # Límites pequeños para probar los bordes: paso ≤ 5000 ms, ≤ 3 pasos, total ≤ 9000 ms.
    m = int(ex.llamar("sp_crear_modelo", ("Modelo V011", None, "ESP32", 3000, 5000, 3, 9000))[0]["id_modelo"])
    ex.llamar("sp_guardar_capacidad", (m, "AVANZAR", 1, None, "movimiento", 1))
    ex.llamar("sp_guardar_capacidad", (m, "LUZ", 10, None, "accesorio", 0))
    ex.llamar("sp_guardar_capacidad", (m, "DETENER", 9, None, "paro", 1))
    v = int(ex.llamar("sp_crear_unidad", (m, "Unidad V011", None, None, "inventario", 1))[0]["id_vehiculo"])
    v2 = int(ex.llamar("sp_crear_unidad", (m, "Otra unidad V011", None, None, "inventario", 1))[0]["id_vehiculo"])
    cmd = {r[1]: r[0] for r in ex.ejecutar("SELECT id_comando, codigo FROM comandos WHERE id_vehiculo = %s", (v,))}
    ajeno = ex.valor("SELECT id_comando FROM comandos WHERE id_vehiculo = %s AND codigo = 1", (v2,))

    lim = ex.llamar("sp_limites_unidad", (v,))[0]
    _afirmar((lim["max_paso_ms"], lim["max_pasos_demo"], lim["max_demo_ms"]) == (5000, 3, 9000), f"sp_limites_unidad: {lim}")
    _afirmar(ex.llamar("sp_limites_unidad", (999999,)) == [], "unidad inexistente")

    # ---- Solo el comprador vigente crea DEMO privadas
    _debe_fallar(lambda: ex.llamar("sp_crear_demo_privada", (v, u, "Mía", None)), ERRNO_SIGNAL, "sin asignación no se crea")
    ex.llamar("sp_asignar_unidad", (v, u, None))
    _debe_fallar(lambda: ex.llamar("sp_crear_demo_privada", (v, otro, "Ajena", None)), ERRNO_SIGNAL, "otro usuario no crea")
    d = int(ex.llamar("sp_crear_demo_privada", (v, u, "Mi DEMO", "prueba"))[0]["id_demo"])
    fila = ex.ejecutar("SELECT ambito, id_propietario, activo FROM demos WHERE id_demo = %s", (d,))[0]
    _afirmar(fila[0] == "privada" and fila[1] == u and fila[2] == 1, f"DEMO privada: {fila}")

    # ---- Pasos: reemplazo atómico y orden del arreglo
    def pasos(lista):
        return ex.llamar("sp_guardar_pasos_demo", (d, json.dumps(lista)))[0]

    r = pasos([{"id_comando": cmd[1], "duracion_ms": 1000, "pausa_ms": 200},
               {"id_comando": cmd[10], "duracion_ms": 500}])
    _afirmar(r["pasos"] == 2 and r["duracion_total_ms"] == 1700, f"guardar 2 pasos: {r}")
    orden = ex.ejecutar("SELECT orden, id_comando, pausa_ms FROM demo_movimientos WHERE id_demo = %s ORDER BY orden", (d,))
    _afirmar(orden == [(1, cmd[1], 200), (2, cmd[10], 0)], f"orden y pausa por defecto: {orden}")
    pasos([{"id_comando": cmd[10], "duracion_ms": 500}, {"id_comando": cmd[1], "duracion_ms": 1000}])   # reordenar
    orden = ex.ejecutar("SELECT orden, id_comando FROM demo_movimientos WHERE id_demo = %s ORDER BY orden", (d,))
    _afirmar(orden == [(1, cmd[10]), (2, cmd[1])], f"reordenar: {orden}")

    # ---- Lo que debe fallar (y NO tocar los pasos guardados)
    casos = [
        ([{"id_comando": cmd[1], "duracion_ms": 1000}] * 4, "más pasos que max_pasos_demo"),
        ([{"id_comando": cmd[1], "duracion_ms": 5001}], "paso más largo que max_paso_ms"),
        ([{"id_comando": cmd[1], "duracion_ms": 1000, "pausa_ms": 6000}], "pausa más larga que max_paso_ms"),
        ([{"id_comando": cmd[1], "duracion_ms": 0}], "duración 0"),
        ([{"id_comando": cmd[1]}], "sin duración"),
        ([{"id_comando": cmd[1], "duracion_ms": 5000}, {"id_comando": cmd[1], "duracion_ms": 4500}], "total > max_demo_ms"),
        ([{"id_comando": ajeno, "duracion_ms": 1000}], "comando de otra unidad"),
        ([{"id_comando": 999999, "duracion_ms": 1000}], "comando inexistente"),
    ]
    for lista, descripcion in casos:
        _debe_fallar(lambda lista=lista: pasos(lista), ERRNO_SIGNAL, descripcion)
    ex.ejecutar("UPDATE comandos SET activo = 0 WHERE id_comando = %s", (cmd[10],))
    _debe_fallar(lambda: pasos([{"id_comando": cmd[10], "duracion_ms": 500}]), ERRNO_SIGNAL, "comando inactivo")
    ex.ejecutar("UPDATE comandos SET activo = 1 WHERE id_comando = %s", (cmd[10],))
    _debe_fallar(lambda: ex.llamar("sp_guardar_pasos_demo", (d, json.dumps({"id_comando": 1}))), ERRNO_SIGNAL, "no es lista")
    _debe_fallar(lambda: ex.llamar("sp_guardar_pasos_demo", (999999, "[]")), ERRNO_SIGNAL, "DEMO inexistente")
    _afirmar(ex.valor("SELECT COUNT(*) FROM demo_movimientos WHERE id_demo = %s", (d,)) == 2,
             "un guardado rechazado no debe borrar los pasos anteriores")
    _afirmar(pasos([])["pasos"] == 0, "se pueden borrar todos los pasos")

    # ---- Máximo 20 DEMO privadas por unidad y comprador
    for i in range(19):
        ex.llamar("sp_crear_demo_privada", (v, u, f"Extra {i}", None))
    _debe_fallar(lambda: ex.llamar("sp_crear_demo_privada", (v, u, "La 21", None)), ERRNO_SIGNAL, "máximo 20")

    # ---- Limpieza
    ex.ejecutar("DELETE FROM demos WHERE id_vehiculo IN (%s, %s)", (v, v2))
    ex.ejecutar("DELETE FROM asignaciones WHERE id_vehiculo IN (%s, %s)", (v, v2))
    ex.llamar("sp_eliminar_vehiculo", (v,))
    ex.llamar("sp_eliminar_vehiculo", (v2,))
    ex.ejecutar("DELETE FROM modelo_comandos WHERE id_modelo = %s", (m,))
    ex.ejecutar("DELETE FROM modelos_vehiculo WHERE id_modelo = %s", (m,))
    ex.ejecutar("DELETE FROM auditoria WHERE id_usuario IN (%s, %s)", (u, otro))
    ex.ejecutar("DELETE FROM usuarios WHERE id_usuario IN (%s, %s)", (u, otro))
    despues = ex.conteos(base)
    _afirmar(antes == despues, f"la prueba dejó registros en las tablas originales: {antes} → {despues}")


def probar_v012(ex, base):
    ex.usar(base)
    antes = ex.conteos(base)
    _afirmar(ex.llamar("sp_version_esquema")[0]["version"] >= 12, "sp_version_esquema debe ser 12 o más")
    # Ninguna prueba debe chocar con una reserva real que hubiera en la copia.
    ex.llamar("sp_invitado_cerrar_todas", ("detenida",))

    m = int(ex.llamar("sp_crear_modelo", ("Modelo V012", "Para invitados", "ESP32", 3000, 5000, 10, 60000))[0]["id_modelo"])
    ex.llamar("sp_guardar_capacidad", (m, "AVANZAR", 1, None, "movimiento", 1))
    ex.llamar("sp_guardar_capacidad", (m, "LUZ", 10, None, "accesorio", 0))
    ex.llamar("sp_guardar_capacidad", (m, "DETENER", 9, None, "paro", 1))
    ve = int(ex.llamar("sp_crear_unidad", (m, "Exhibición V012", None, None, "exhibicion", 1))[0]["id_vehiculo"])
    vi = int(ex.llamar("sp_crear_unidad", (m, "Inventario V012", None, None, "inventario", 1))[0]["id_vehiculo"])
    h = lambda t: hashlib.sha256(f"v012-{t}".encode()).hexdigest()   # noqa: E731
    redes = [h("red1"), h("red2"), h("red3")]

    catalogo = {f["id_vehiculo"]: f for f in ex.llamar("sp_catalogo_exhibicion")}
    _afirmar(ve in catalogo and vi not in catalogo, "el catálogo solo muestra unidades en exhibición")
    _afirmar(catalogo[ve]["reservada_hasta"] is None and catalogo[ve]["modelo"] == "Modelo V012", f"catálogo: {catalogo[ve]}")

    def reservar(v, token, red, minutos=5, por_hora=3, enfriamiento=10):
        return ex.llamar("sp_invitado_reservar", (v, h(token), red, minutos, por_hora, _espera(ex, enfriamiento)))[0]

    # ---- Solo unidades en exhibición (nunca la de un comprador ni una en inventario)
    _afirmar(reservar(vi, "t0", redes[0])["resultado"] == "no_disponible", "unidad en inventario")
    _afirmar(reservar(999999, "t0", redes[0])["resultado"] == "no_disponible", "unidad inexistente")

    # ---- Reserva exclusiva
    r1 = reservar(ve, "t1", redes[0])
    _afirmar(r1["resultado"] == "ok" and r1["segundos"] == 300 and r1["id_reserva"], f"reservar: {r1}")
    ocupada = reservar(ve, "t2", redes[1])
    _afirmar(ocupada["resultado"] == "ocupada" and 0 < ocupada["segundos"] <= 300, f"ocupada: {ocupada}")
    fila = next(f for f in ex.llamar("sp_catalogo_exhibicion") if f["id_vehiculo"] == ve)
    _afirmar(fila["reservada_hasta"] is not None and fila["segundos_reserva"] > 0, f"el catálogo muestra la reserva: {fila}")
    s = ex.llamar("sp_invitado_sesion", (h("t1"),))
    _afirmar(len(s) == 1 and s[0]["id_vehiculo"] == ve and s[0]["segundos_restantes"] > 290, f"sesión vigente: {s}")
    _afirmar(ex.llamar("sp_invitado_sesion", (h("t2"),)) == [], "un token sin reserva no tiene sesión")

    # ---- Comandos permitidos: AVANZAR y DETENER, no LUZ
    _afirmar({c["codigo"] for c in ex.llamar("sp_comandos_invitado", (ve,))} == {1, 9}, "comandos de invitado")

    # ---- Terminar
    _afirmar(ex.llamar("sp_invitado_finalizar", (r1["id_reserva"], "cancelada"))[0]["finalizadas"] == 1, "finalizar")
    _afirmar(ex.llamar("sp_invitado_finalizar", (r1["id_reserva"], "cancelada"))[0]["finalizadas"] == 0, "finalizar dos veces")
    _afirmar(ex.llamar("sp_invitado_sesion", (h("t1"),)) == [], "tras terminar ya no hay sesión")

    # ---- Abuso desde la misma red: enfriamiento y límite por hora
    e = reservar(ve, "t3", redes[0])
    _afirmar(e["resultado"] == "enfriamiento" and e["segundos"] > 500, f"enfriamiento: {e}")
    lim = reservar(ve, "t3", redes[0], por_hora=1, enfriamiento=0)
    _afirmar(lim["resultado"] == "limite" and lim["segundos"] > 0, f"límite por hora: {lim}")

    # ---- Una reserva vencida se cierra sola al reservar otro invitado
    r2 = reservar(ve, "t4", redes[1])
    _afirmar(r2["resultado"] == "ok", f"otra red sí puede: {r2}")
    ex.ejecutar("UPDATE reservas_exhibicion SET inicio = UTC_TIMESTAMP() - INTERVAL 10 MINUTE, "
                "expira_en = UTC_TIMESTAMP() - INTERVAL 1 MINUTE WHERE id_reserva = %s", (r2["id_reserva"],))
    _afirmar(ex.llamar("sp_invitado_sesion", (h("t4"),)) == [], "una reserva vencida no da sesión")
    r3 = reservar(ve, "t5", redes[2])
    _afirmar(r3["resultado"] == "ok", f"tras vencer, la unidad queda libre: {r3}")
    _afirmar(ex.valor("SELECT motivo_fin FROM reservas_exhibicion WHERE id_reserva = %s", (r2["id_reserva"],)) == "expirada",
             "la vencida queda como «expirada»")

    # ---- Al arrancar la API se cierran todas
    _afirmar(ex.llamar("sp_invitado_cerrar_todas", ("detenida",))[0]["finalizadas"] >= 1, "cerrar todas")
    _afirmar(ex.llamar("sp_invitado_sesion", (h("t5"),)) == [], "tras cerrar todas no queda sesión")

    # ---- Limpieza
    ex.ejecutar("DELETE r FROM reservas_exhibicion r JOIN sesiones_invitado s ON s.id_sesion = r.id_sesion "
                "WHERE s.red_hash IN (%s, %s, %s)", tuple(redes))
    ex.ejecutar("DELETE FROM sesiones_invitado WHERE red_hash IN (%s, %s, %s)", tuple(redes))
    ex.llamar("sp_eliminar_vehiculo", (ve,))
    ex.llamar("sp_eliminar_vehiculo", (vi,))
    ex.ejecutar("DELETE FROM modelo_comandos WHERE id_modelo = %s", (m,))
    ex.ejecutar("DELETE FROM modelos_vehiculo WHERE id_modelo = %s", (m,))
    despues = ex.conteos(base)
    _afirmar(antes == despues, f"la prueba dejó registros en las tablas originales: {antes} → {despues}")


def probar_v013(ex, base):
    ex.usar(base)
    antes = ex.conteos(base)
    _afirmar(ex.llamar("sp_version_esquema")[0]["version"] >= 13, "sp_version_esquema debe ser 13 o más")
    m = int(ex.llamar("sp_crear_modelo", ("Modelo V013", None, "ESP32", 3000, 5000, 10, 60000))[0]["id_modelo"])
    v = int(ex.llamar("sp_crear_unidad", (m, "Unidad V013", None, None, "inventario", 1))[0]["id_vehiculo"])
    v2 = int(ex.llamar("sp_crear_unidad", (m, "Otra V013", None, None, "inventario", 1))[0]["id_vehiculo"])
    h = lambda t: hashlib.sha256(f"v013-{t}".encode()).hexdigest()   # noqa: E731

    _afirmar(ex.llamar("sp_dispositivo_estado", (v,)) == [], "sin credencial al inicio")
    _debe_fallar(lambda: ex.llamar("sp_dispositivo_crear", (999999, h("x"))), ERRNO_SIGNAL, "unidad inexistente")
    c1 = int(ex.llamar("sp_dispositivo_crear", (v, h("a")))[0]["id_credencial"])
    valida = ex.llamar("sp_dispositivo_validar", (h("a"),))
    _afirmar(len(valida) == 1 and valida[0]["id_vehiculo"] == v, f"validar: {valida}")
    _afirmar(ex.valor("SELECT ultimo_uso IS NOT NULL FROM credenciales_dispositivo WHERE id_credencial = %s", (c1,)) == 1,
             "validar marca el último uso")
    _afirmar(ex.llamar("sp_dispositivo_validar", (h("nada"),)) == [], "un secreto desconocido no valida")

    # Una nueva credencial revoca la anterior (una vigente por unidad)
    c2 = int(ex.llamar("sp_dispositivo_crear", (v, h("b")))[0]["id_credencial"])
    _afirmar(ex.llamar("sp_dispositivo_validar", (h("a"),)) == [], "la credencial anterior ya no sirve")
    est = ex.llamar("sp_dispositivo_estado", (v,))[0]
    _afirmar(est["id_credencial"] == c2 and est["vigente"] == 1, f"estado: {est}")
    _debe_fallar(lambda: ex.llamar("sp_dispositivo_crear", (v2, h("b"))), 1062, "el mismo secreto no sirve para otra unidad")

    _afirmar(ex.llamar("sp_dispositivo_revocar", (v,))[0]["revocadas"] == 1, "revocar")
    _afirmar(ex.llamar("sp_dispositivo_validar", (h("b"),)) == [], "revocada no valida")
    _afirmar(ex.llamar("sp_dispositivo_estado", (v,))[0]["vigente"] == 0, "estado tras revocar")
    _afirmar(ex.llamar("sp_dispositivo_revocar", (v,))[0]["revocadas"] == 0, "revocar dos veces")

    ex.ejecutar("DELETE FROM credenciales_dispositivo WHERE id_vehiculo IN (%s, %s)", (v, v2))
    ex.llamar("sp_eliminar_vehiculo", (v,))
    ex.llamar("sp_eliminar_vehiculo", (v2,))
    ex.ejecutar("DELETE FROM modelos_vehiculo WHERE id_modelo = %s", (m,))
    despues = ex.conteos(base)
    _afirmar(antes == despues, f"la prueba dejó registros en las tablas originales: {antes} → {despues}")


def probar_v014(ex, base):
    ex.usar(base)
    antes = ex.conteos(base)
    _afirmar(ex.llamar("sp_version_esquema")[0]["version"] >= 14, "sp_version_esquema debe ser 14 o más")
    ex.llamar("sp_invitado_cerrar_todas", ("detenida",))
    m = int(ex.llamar("sp_crear_modelo", ("Modelo V014", None, "ESP32", 3000, 5000, 10, 60000))[0]["id_modelo"])
    ve = int(ex.llamar("sp_crear_unidad", (m, "Exhibición V014", None, None, "exhibicion", 1))[0]["id_vehiculo"])
    h = lambda t: hashlib.sha256(f"v014-{t}".encode()).hexdigest()   # noqa: E731
    red_a, red_b = h("red-a"), h("red-b")
    n = iter(range(100))

    def reservar(red, por_hora=10):
        return ex.llamar("sp_invitado_reservar", (ve, h(f"t{next(n)}"), red, 5, por_hora, _espera(ex, 10)))[0]

    r = reservar(red_a)
    _afirmar(r["resultado"] == "ok", f"primera reserva: {r}")
    _afirmar(reservar(red_a)["resultado"] == "propia", "la misma red ve su propia reserva, no «ocupada»")
    _afirmar(reservar(red_b)["resultado"] == "ocupada", "otra red: ocupada")

    # Terminó por desconexión / reinicio / empresa → sin espera
    for motivo in ("desconexion", "detenida", "admin"):
        ex.llamar("sp_invitado_finalizar", (r["id_reserva"], motivo))
        r = reservar(red_a)
        _afirmar(r["resultado"] == "ok", f"tras «{motivo}» se puede volver a reservar enseguida: {r}")

    # La usó o la cerró el visitante → espera de 10 min
    ex.llamar("sp_invitado_finalizar", (r["id_reserva"], "cancelada"))
    e = reservar(red_a)
    _afirmar(e["resultado"] == "enfriamiento" and e["segundos"] > 500, f"tras «cancelada» hay espera: {e}")
    # El límite por hora sigue contando todas
    _afirmar(reservar(red_a, por_hora=4)["resultado"] == "limite", "el límite por hora cuenta todas las reservas")

    ex.ejecutar("DELETE r FROM reservas_exhibicion r JOIN sesiones_invitado s ON s.id_sesion = r.id_sesion "
                "WHERE s.red_hash IN (%s, %s)", (red_a, red_b))
    ex.ejecutar("DELETE FROM sesiones_invitado WHERE red_hash IN (%s, %s)", (red_a, red_b))
    ex.llamar("sp_eliminar_vehiculo", (ve,))
    ex.ejecutar("DELETE FROM modelos_vehiculo WHERE id_modelo = %s", (m,))
    despues = ex.conteos(base)
    _afirmar(antes == despues, f"la prueba dejó registros en las tablas originales: {antes} → {despues}")


def probar_v015(ex, base):
    """Una unidad CON TODO (historial, DEMO con pasos, asignación pasada, soporte, reserva y
    credencial) solo se elimina dada de baja, y entonces no deja nada suyo en la base."""
    ex.usar(base)
    antes = ex.conteos(base)
    _afirmar(ex.llamar("sp_version_esquema")[0]["version"] >= 15, "sp_version_esquema debe ser 15 o más")
    ex.llamar("sp_invitado_cerrar_todas", ("detenida",))
    h = lambda t: hashlib.sha256(f"v015-{t}".encode()).hexdigest()   # noqa: E731
    futuro = ex.valor("SELECT UTC_TIMESTAMP() + INTERVAL 1 DAY")
    u = int(ex.llamar("sp_crear_usuario", ("cliente.v015@prueba.local", "Cliente V015", "usuario"))[0]["id_usuario"])
    a = int(ex.llamar("sp_crear_usuario", ("admin.v015@prueba.local", "Admin V015", "admin"))[0]["id_usuario"])
    m = int(ex.llamar("sp_crear_modelo", ("Modelo V015", None, "ESP32", 3000, 5000, 10, 60000))[0]["id_modelo"])
    ex.llamar("sp_guardar_capacidad", (m, "AVANZAR", 1, None, "movimiento", 1))
    ex.llamar("sp_guardar_capacidad", (m, "DETENER", 9, None, "paro", 1))
    v = int(ex.llamar("sp_crear_unidad", (m, "Unidad V015", None, None, "exhibicion", 1))[0]["id_vehiculo"])
    avanzar = ex.valor("SELECT id_comando FROM comandos WHERE id_vehiculo = %s AND codigo = 1", (v,))

    # Vida completa: reserva de invitado, venta, soporte, DEMO privada con pasos, historial, credencial
    r = ex.llamar("sp_invitado_reservar", (v, h("token"), h("red"), 1, 10, _espera(ex, 3)))[0]
    _afirmar(r["resultado"] == "ok", f"reserva: {r}")
    ex.llamar("sp_invitado_finalizar", (r["id_reserva"], "cancelada"))
    a1 = int(ex.llamar("sp_asignar_unidad", (v, u, a))[0]["id_asignacion"])
    ex.llamar("sp_soporte_otorgar", (v, u, a, "prueba", futuro))
    d = int(ex.llamar("sp_crear_demo_privada", (v, u, "DEMO V015", None))[0]["id_demo"])
    ex.llamar("sp_guardar_pasos_demo", (d, json.dumps([{"id_comando": avanzar, "duracion_ms": 1000, "pausa_ms": 0}])))
    ex.llamar("sp_registrar_historial_autor", (v, avanzar, "PRUEBA_V015", u, None))
    ex.llamar("sp_actualizar_estado", (v, avanzar, 0))
    ex.llamar("sp_dispositivo_crear", (v, h("secreto")))

    # Sin baja no se elimina (ni con comprador ni sin él)
    _debe_fallar(lambda: ex.llamar("sp_eliminar_unidad_baja", (v,)), ERRNO_SIGNAL, "vendida: no se elimina")
    ex.llamar("sp_finalizar_asignacion", (a1, "prueba", "inventario"))
    _debe_fallar(lambda: ex.llamar("sp_eliminar_unidad_baja", (v,)), ERRNO_SIGNAL, "en inventario: no se elimina")
    _debe_fallar(lambda: ex.llamar("sp_eliminar_unidad_baja", (999999,)), ERRNO_SIGNAL, "unidad inexistente")
    _afirmar(ex.valor("SELECT COUNT(*) FROM historial_comandos WHERE id_vehiculo = %s", (v,)) == 1,
             "un intento rechazado no borra nada")

    ex.llamar("sp_baja_unidad", (v,))
    borrado = ex.llamar("sp_eliminar_unidad_baja", (v,))[0]
    _afirmar((borrado["historial"], borrado["demos"], borrado["asignaciones"], borrado["reservas"]) == (1, 1, 1, 1),
             f"conteos de lo borrado: {borrado}")
    for tabla in ("vehiculos", "comandos", "historial_comandos", "estado_vehiculo", "demos", "asignaciones",
                  "autorizaciones_soporte", "reservas_exhibicion", "credenciales_dispositivo"):
        _afirmar(ex.valor(f"SELECT COUNT(*) FROM {tabla} WHERE id_vehiculo = %s", (v,)) == 0,
                 f"quedaron filas de la unidad en {tabla}")
    _afirmar(ex.valor("SELECT COUNT(*) FROM demo_movimientos WHERE id_demo = %s", (d,)) == 0, "quedaron pasos de la DEMO")

    # ---- Limpieza
    ex.ejecutar("DELETE FROM sesiones_invitado WHERE red_hash = %s", (h("red"),))
    ex.ejecutar("DELETE FROM modelo_comandos WHERE id_modelo = %s", (m,))
    ex.ejecutar("DELETE FROM modelos_vehiculo WHERE id_modelo = %s", (m,))
    ex.ejecutar("DELETE FROM usuarios WHERE id_usuario IN (%s, %s)", (u, a))
    despues = ex.conteos(base)
    _afirmar(antes == despues, f"la prueba dejó registros en las tablas originales: {antes} → {despues}")


def probar_v017(ex, base):
    """La espera entre reservas se mide en SEGUNDOS (15 s en la API)."""
    ex.usar(base)
    antes = ex.conteos(base)
    _afirmar(ex.llamar("sp_version_esquema")[0]["version"] >= 17, "sp_version_esquema debe ser 17 o más")
    ex.llamar("sp_invitado_cerrar_todas", ("detenida",))
    m = int(ex.llamar("sp_crear_modelo", ("Modelo V017", None, "ESP32", 3000, 5000, 10, 60000))[0]["id_modelo"])
    ve = int(ex.llamar("sp_crear_unidad", (m, "Exhibición V017", None, None, "exhibicion", 1))[0]["id_vehiculo"])
    h = lambda t: hashlib.sha256(f"v017-{t}".encode()).hexdigest()   # noqa: E731
    red = h("red")
    n = iter(range(100))

    def reservar(espera_s):
        return ex.llamar("sp_invitado_reservar", (ve, h(f"t{next(n)}"), red, 2, 10, espera_s))[0]

    r = reservar(15)
    _afirmar(r["resultado"] == "ok" and 110 < r["segundos"] <= 120, f"reserva de 2 minutos: {r}")
    ex.llamar("sp_invitado_finalizar", (r["id_reserva"], "cancelada"))
    e = reservar(15)
    _afirmar(e["resultado"] == "enfriamiento" and 1 <= e["segundos"] <= 15, f"espera de 15 s (no 15 min): {e}")
    _afirmar(reservar(0)["resultado"] == "ok", "con espera 0 se reserva enseguida")

    ex.ejecutar("DELETE r FROM reservas_exhibicion r JOIN sesiones_invitado s ON s.id_sesion = r.id_sesion "
                "WHERE s.red_hash = %s", (red,))
    ex.ejecutar("DELETE FROM sesiones_invitado WHERE red_hash = %s", (red,))
    ex.llamar("sp_eliminar_vehiculo", (ve,))
    ex.ejecutar("DELETE FROM modelos_vehiculo WHERE id_modelo = %s", (m,))
    despues = ex.conteos(base)
    _afirmar(antes == despues, f"la prueba dejó registros en las tablas originales: {antes} → {despues}")


# versión → función(ejecutor, base_de_la_copia)
PRUEBAS = {
    "V009": probar_v009,
    "V010": probar_v010,
    "V011": probar_v011,
    "V012": probar_v012,
    "V013": probar_v013,
    "V014": probar_v014,
    "V015": probar_v015,
    "V017": probar_v017,
}
