"""Pruebas de los procedimientos nuevos, por versión de migración.

`python -m app.db.migrar probar` las ejecuta SOLO en la copia de prueba,
después de aplicar la versión y otra vez al reaplicar. Cada prueba crea
datos marcados como de prueba, comprueba reglas de negocio (también las que
deben FALLAR) y borra todo lo que creó: las tablas originales deben quedar
con el mismo número de registros.
"""

import json

import mysql.connector

ERRNO_SIGNAL = 1644          # SIGNAL SQLSTATE '45000' (regla de negocio)
ERRNO_FK_PADRE = 1451        # no se puede borrar: registro en uso


class FallaPrueba(Exception):
    pass


def _afirmar(condicion, mensaje):
    if not condicion:
        raise FallaPrueba(mensaje)


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
    _afirmar(ex.llamar("sp_version_esquema")[0]["version"] == 9, "sp_version_esquema no devuelve 9")

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


# versión → función(ejecutor, base_de_la_copia)
PRUEBAS = {
    "V009": probar_v009,
}
