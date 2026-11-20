import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.documentacion import ETIQUETAS
from app.api.routes import (
    admin, auth, comandos, control, demos, estado, historial, invitado, movimientos, sistema, vehiculos, ws,
)
from app.contenedor import Contenedor
from app.core.config import origenes_cors
from app.core.exceptions import ErrorAplicacion

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app")

DESCRIPCION = """
API local para gestionar un **vehículo IoT** (FastAPI + Amazon RDS).

* **GET** consultan; **POST** escriben, actualizan y ejecutan acciones.
* **Sesión** (`/auth`): correo + contraseña → token de acceso corto
  (`Authorization: Bearer …`) + token de renovación que rota en cada uso.
* **Autorización por unidad**: el comprador solo ve y opera SUS unidades;
  el administrador opera unidades en inventario/exhibición y una vendida
  solo con autorización de soporte vigente del comprador.
* Transición (se retira en la Etapa 9): la cabecera `X-API-Key` sigue
  aceptándose para escrituras y control; eliminar exige la de administrador.
* Con `CONTROL_ABIERTO=true` (en `.env`), **solo** mover, iniciar/cancelar
  DEMO y `GET /sesion` se aceptan sin clave; crear, editar y eliminar la
  siguen exigiendo.
* **Movimiento individual**: actualiza `estado_vehiculo` **y** guarda en
  `historial_comandos`.
* **DEMO**: se transmite por WebSocket y **no** se guarda en el historial.
* **Administración** (`/admin`): modelos, unidades, clientes, asignaciones,
  auditoría y métricas. Requiere la migración V009 en la base.
* WebSocket (no aparece aquí): `ws://localhost:8000/ws/vehiculos/{id}`
  — ver README.
"""


def crear_app(fabrica_contenedor=Contenedor):
    """Construye la aplicación. Las pruebas pasan una fábrica con un repositorio falso."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.contenedor = fabrica_contenedor()

        try:
            app.state.contenedor.verificar_base_datos()
            logger.info("Conexión a RDS verificada · versión del esquema: %s",
                        app.state.contenedor.esquema.version())
        except Exception as error:
            # La API arranca igualmente; /health/db mostrará el problema.
            logger.warning(
                "No se pudo verificar RDS al arrancar (%s).",
                error.__class__.__name__,
            )

        # Reservas de invitado: cierra las previas y arranca el vigilante (caducidad / desconexión).
        await app.state.contenedor.invitados.iniciar()
        # Revalidación periódica de las suscripciones WebSocket (permisos que cambian).
        await app.state.contenedor.canal.iniciar()

        yield

        await app.state.contenedor.canal.cerrar()
        await app.state.contenedor.invitados.cerrar()
        await app.state.contenedor.demo_ejecutor.cerrar()

    app = FastAPI(
        title="API Vehículo IoT",
        description=DESCRIPCION,
        version="1.3.0",
        openapi_tags=ETIQUETAS,
        lifespan=lifespan,
    )

    # CORS para el frontend en GitHub Pages. Solo los métodos y cabeceras que
    # usa el cliente; sin cookies (allow_credentials=False): el token viaja en
    # la cabecera Authorization, no en cookies. No afecta al WebSocket.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origenes_cors(),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key", "Authorization", "X-Invitado"],
        # (X-Dispositivo no: solo lo usa el ESP32, nunca un navegador)
        allow_credentials=False,
        max_age=600,
    )

    @app.exception_handler(ErrorAplicacion)
    async def manejar_error_aplicacion(request: Request, error: ErrorAplicacion):
        if error.codigo_http >= 500:
            logger.error("%s %s -> %s", request.method, request.url.path,
                         error.codigo_http)

        return JSONResponse(
            status_code=error.codigo_http,
            content={"detail": error.mensaje},
            headers={"WWW-Authenticate": "Bearer"} if error.codigo_http == 401 else None,
        )

    @app.exception_handler(Exception)
    async def manejar_error_inesperado(request: Request, error: Exception):
        # El detalle va al log local; el cliente solo ve un mensaje genérico.
        logger.error(
            "Error no controlado en %s %s", request.method, request.url.path,
            exc_info=error,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Error interno del servidor."},
        )

    for modulo in (sistema, auth, invitado, vehiculos, comandos, estado, historial,
                   movimientos, demos, control, admin, ws):
        app.include_router(modulo.router)

    return app


app = crear_app()
