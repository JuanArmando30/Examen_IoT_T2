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
TAG_ADMIN = "Administración"
TAG_SESION = "Sesión"
TAG_MIS = "Mis vehículos"
TAG_INVITADO = "Invitado"
TAG_TIEMPO_REAL = "Tiempo real"

ETIQUETAS = [
    {"name": TAG_SESION,
     "description": "Inicio de sesión con correo y contraseña: token de acceso corto "
                    "(Bearer, en memoria) + token de renovación que rota en cada uso. "
                    "Requiere TOKEN_SECRETO en .env y la migración V010."},
    {"name": TAG_MIS,
     "description": "Unidades asignadas al comprador con sesión y autorización de "
                    "soporte (consentimiento temporal para que la empresa la opere)."},
    {"name": TAG_TIEMPO_REAL,
     "description": "WebSocket por unidad: ticket de un solo uso para el navegador (mismas reglas "
                    "que REST) y credencial propia del ESP32 (cabecera X-Dispositivo)."},
    {"name": TAG_INVITADO,
     "description": "Visitante sin cuenta: catálogo público y reserva exclusiva y temporal de la "
                    "unidad de exhibición (cuando la empresa la abre). Token en la cabecera X-Invitado."},
    {"name": TAG_ADMIN,
     "description": "Inventario de la empresa: modelos y sus capacidades, unidades "
                    "físicas, clientes, asignaciones, auditoría y métricas. Requiere la "
                    "token de un administrador (o, en transición, la clave X-API-Key de "
                    "administrador). Responde "
                    "503 si la base aún no tiene las migraciones V001–V009. SP de V009."},
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
R401 = {401: _r("Sin sesión válida: falta el token Bearer (o la cabecera X-API-Key), "
                "o es inválido o venció.")}
R403 = {403: _r("Hay sesión, pero sin permiso para esa unidad u operación.")}
R429 = {429: _r("Demasiados intentos: espera y vuelve a probar.")}
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
R503_ADMIN = {503: _r("Amazon RDS no disponible, o la base aún no tiene las "
                      "migraciones de Administración (V001–V009).")}
ADMIN_LECTURA = {**R401, **R403, **R404, **R422, **R500, **R503_ADMIN}
ADMIN_ESCRITURA = {**R400, **R401, **R403, **R404, **R409, **R422, **R500, **R503_ADMIN}

R503_SESION = {503: _r("Inicio de sesión no configurado (TOKEN_SECRETO), base sin la "
                       "migración V010 o Amazon RDS no disponible.")}
SESION = {**R400, **R401, **R422, **R429, **R500, **R503_SESION}
SESION_PRIVADA = {**R400, **R401, **R403, **R404, **R409, **R422, **R429, **R500, **R503_SESION}
