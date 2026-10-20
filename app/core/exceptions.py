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
