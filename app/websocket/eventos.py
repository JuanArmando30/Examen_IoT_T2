"""Mensajes JSON que viajan por WebSocket.

Todos tienen la misma forma:
{
  "evento": "<tipo>", "id_vehiculo": 1, "comando": "AVANZAR" | null,
  "codigo": 1 | null, "timestamp": "<ISO-8601 UTC>", "datos": { ... }
}
"""

from datetime import date, datetime, timezone

ESTADO_INICIAL = "estado_inicial"
ESTADO_ACTUALIZADO = "estado_actualizado"
MOVIMIENTO_INDIVIDUAL = "movimiento_individual"
DEMO_INICIADA = "demo_iniciada"
DEMO_MOVIMIENTO = "demo_movimiento"
DEMO_FINALIZADA = "demo_finalizada"
DEMO_CANCELADA = "demo_cancelada"
ERROR = "error"
PONG = "pong"


def _serializable(valor):
    """Convierte fechas a texto ISO para poder usar json.dumps."""

    if isinstance(valor, (datetime, date)):
        return valor.isoformat()

    if isinstance(valor, dict):
        return {k: _serializable(v) for k, v in valor.items()}

    if isinstance(valor, (list, tuple)):
        return [_serializable(v) for v in valor]

    return valor


def construir(evento, id_vehiculo, comando=None, codigo=None, datos=None):
    return {
        "evento": evento,
        "id_vehiculo": id_vehiculo,
        "comando": comando,
        "codigo": codigo,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "datos": _serializable(datos or {}),
    }


def estado_inicial(id_vehiculo, estado):
    """estado = fila de sp_obtener_estado o None si aún no hay estado."""

    if estado is None:
        return construir(
            ESTADO_INICIAL, id_vehiculo,
            datos={"conectado": False, "fecha_actualizacion": None,
                   "mensaje": "El vehículo aún no tiene un estado registrado."},
        )

    return construir(
        ESTADO_INICIAL, id_vehiculo,
        comando=estado["comando"], codigo=estado["codigo"],
        datos={"conectado": bool(estado["conectado"]),
               "fecha_actualizacion": estado["fecha_actualizacion"]},
    )


def estado_actualizado(id_vehiculo, estado):
    evento = estado_inicial(id_vehiculo, estado)
    evento["evento"] = ESTADO_ACTUALIZADO
    return evento


def movimiento_individual(resultado):
    return construir(
        MOVIMIENTO_INDIVIDUAL, resultado["id_vehiculo"],
        comando=resultado["comando"], codigo=resultado["codigo"],
        datos={"origen": resultado["origen"],
               "conectado": resultado["conectado"],
               "fecha_actualizacion": resultado["fecha_actualizacion"],
               "registrado_en_historial": True},
    )


def demo_iniciada(id_vehiculo, demo, total, duracion_estimada_ms):
    return construir(
        DEMO_INICIADA, id_vehiculo,
        datos={"id_demo": demo["id_demo"], "nombre": demo["nombre"],
               "total_movimientos": total,
               "duracion_estimada_ms": duracion_estimada_ms},
    )


def demo_movimiento(id_vehiculo, id_demo, movimiento, total):
    return construir(
        DEMO_MOVIMIENTO, id_vehiculo,
        comando=movimiento["comando"], codigo=movimiento["codigo"],
        datos={"id_demo": id_demo, "orden": movimiento["orden"],
               "total_movimientos": total,
               "duracion_ms": movimiento["duracion_ms"],
               "pausa_ms": movimiento["pausa_ms"],
               "registrado_en_historial": False},
    )


def demo_finalizada(id_vehiculo, id_demo, ejecutados):
    return construir(
        DEMO_FINALIZADA, id_vehiculo,
        datos={"id_demo": id_demo, "movimientos_ejecutados": ejecutados,
               "registrado_en_historial": False},
    )


def demo_cancelada(id_vehiculo, id_demo, ejecutados, comando_final):
    return construir(
        DEMO_CANCELADA, id_vehiculo,
        comando=comando_final["nombre"] if comando_final else None,
        codigo=comando_final["codigo"] if comando_final else None,
        datos={"id_demo": id_demo, "movimientos_ejecutados": ejecutados,
               "detenido_con": (
                   comando_final["nombre"] if comando_final else None)},
    )


def error(id_vehiculo, codigo_error, detalle, id_demo=None):
    return construir(
        ERROR, id_vehiculo,
        datos={"codigo_error": codigo_error, "detalle": detalle,
               "id_demo": id_demo},
    )


def pong(id_vehiculo):
    return construir(PONG, id_vehiculo)
