"""Textos y respuestas de error reutilizados en Swagger UI."""

from app.models.schemas import ErrorOut

TAG_SISTEMA = "Sistema"
TAG_VEHICULOS = "Vehículos"
TAG_COMANDOS = "Comandos"
TAG_ESTADO = "Estado"
TAG_HISTORIAL = "Historial"
TAG_MOVIMIENTOS = "Movimiento individual"
TAG_DEMO = "DEMO"
TAG_MOV_DEMO = "Movimientos de DEMO"

ETIQUETAS = [
    {"name": TAG_SISTEMA, "description": "Comprobación del servicio y de RDS."},
    {"name": TAG_VEHICULOS,
     "description": "CRUD de vehículos. SP: sp_crear_vehiculo, "
                    "sp_obtener_vehiculos, sp_obtener_vehiculo, "
                    "sp_actualizar_vehiculo, sp_eliminar_vehiculo."},
    {"name": TAG_COMANDOS,
     "description": "Catálogo de comandos de cada vehículo. SP: "
                    "sp_crear_comando, sp_obtener_comandos_vehiculo, "
                    "sp_actualizar_comando, sp_eliminar_comando."},
    {"name": TAG_ESTADO,
     "description": "Último estado registrado. SP: sp_obtener_estado, "
                    "sp_actualizar_estado."},
    {"name": TAG_HISTORIAL,
     "description": "Bitácora de movimientos individuales (máx. 10). SP: "
                    "sp_obtener_historial."},
    {"name": TAG_MOVIMIENTOS,
     "description": "Ejecuta UN movimiento: estado + historial en una "
                    "transacción y notificación WebSocket."},
    {"name": TAG_DEMO,
     "description": "Secuencias de movimientos. SP: sp_crear_demo, "
                    "sp_obtener_demos, sp_actualizar_demo, sp_eliminar_demo. "
                    "Los movimientos de DEMO NO se guardan en el historial."},
    {"name": TAG_MOV_DEMO,
     "description": "Los N movimientos de una DEMO. SP: "
                    "sp_agregar_movimiento_demo, sp_obtener_movimientos_demo, "
                    "sp_actualizar_movimiento_demo, "
                    "sp_eliminar_movimiento_demo."},
]


def _r(descripcion):
    return {"model": ErrorOut, "description": descripcion}


R400 = {400: _r("Solicitud inválida (referencia inexistente o valor fuera "
                "de rango).")}
R401 = {401: _r("Falta la cabecera X-API-Key o la clave es inválida.")}
R403 = {403: _r("La clave no tiene permisos de administrador.")}
R404 = {404: _r("Recurso no encontrado.")}
R409 = {409: _r("Conflicto con el estado actual (duplicado, inactivo, "
                "DEMO en curso, recurso en uso...).")}
R422 = {422: {"description": "Error de validación del cuerpo o los "
                            "parámetros."}}
R500 = {500: _r("Error interno (sin detalles sensibles).")}
R503 = {503: _r("Amazon RDS no disponible.")}

BASE = {**R500, **R503}
LECTURA = {**R404, **BASE}
ESCRITURA = {**R401, **R404, **R409, **R422, **R400, **BASE}
BORRADO = {**R401, **R403, **R404, **R409, **BASE}
