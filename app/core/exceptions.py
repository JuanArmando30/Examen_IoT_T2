"""Excepciones de negocio.

Los servicios y el repositorio lanzan estas excepciones; main.py las
traduce a respuestas HTTP. Así la lógica no depende de FastAPI.
"""


class ErrorAplicacion(Exception):
    """Error base de la aplicación."""

    codigo_http = 500
    mensaje_por_defecto = "Error interno del servidor."

    def __init__(self, mensaje=None):
        self.mensaje = mensaje or self.mensaje_por_defecto
        super().__init__(self.mensaje)


class SolicitudInvalida(ErrorAplicacion):
    """La solicitud es sintácticamente válida pero no se puede atender."""

    codigo_http = 400
    mensaje_por_defecto = "Solicitud inválida."


class RecursoNoEncontrado(ErrorAplicacion):
    codigo_http = 404
    mensaje_por_defecto = "Recurso no encontrado."


class ConflictoNegocio(ErrorAplicacion):
    """Choca con el estado actual (duplicado, inactivo, DEMO en curso...)."""

    codigo_http = 409
    mensaje_por_defecto = "La operación entra en conflicto con el estado actual."


class ErrorBaseDatos(ErrorAplicacion):
    codigo_http = 500
    mensaje_por_defecto = "Error al procesar la operación en la base de datos."


class BaseDatosNoDisponible(ErrorAplicacion):
    codigo_http = 503
    mensaje_por_defecto = "La base de datos no está disponible en este momento."


class NoAutorizado(ErrorAplicacion):
    """Sin sesión válida (token ausente, vencido o inválido)."""

    codigo_http = 401
    mensaje_por_defecto = "Inicia sesión para continuar."


class Prohibido(ErrorAplicacion):
    """Hay sesión, pero no permiso sobre ese recurso."""

    codigo_http = 403
    mensaje_por_defecto = "No tienes permiso para esta unidad u operación."


class DemasiadosIntentos(ErrorAplicacion):
    codigo_http = 429
    mensaje_por_defecto = "Demasiados intentos. Espera unos minutos y vuelve a probar."


class NoConfigurado(ErrorAplicacion):
    codigo_http = 503
    mensaje_por_defecto = (
        "El inicio de sesión no está configurado en el servidor (falta TOKEN_SECRETO en .env)."
    )


class EsquemaPendiente(ErrorAplicacion):
    """La base aún no tiene las migraciones que necesita esta función."""

    codigo_http = 503
    mensaje_por_defecto = (
        "La base de datos aún no tiene las migraciones de Administración "
        "(V001–V009). Aplícalas con: python -m app.db.migrar aplicar."
    )
