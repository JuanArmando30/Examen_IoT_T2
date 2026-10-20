import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.documentacion import ETIQUETAS
from app.api.routes import (
    comandos, demos, estado, historial, movimientos, sistema, vehiculos, ws,
)
from app.contenedor import Contenedor
from app.core.exceptions import ErrorAplicacion

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app")

DESCRIPCION = """
API local para gestionar un **vehículo IoT** (FastAPI + Amazon RDS).

* **GET** consultan; **POST** escriben, actualizan y ejecutan acciones.
* Las operaciones de escritura y control exigen la cabecera `X-API-Key`
  (botón **Authorize**). Eliminar exige la clave de administrador.
* **Movimiento individual**: actualiza `estado_vehiculo` **y** guarda en
  `historial_comandos`.
* **DEMO**: se transmite por WebSocket y **no** se guarda en el historial.
* WebSocket (no aparece aquí): `ws://localhost:8000/ws/vehiculos/{id}`
  — ver README.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.contenedor = Contenedor()

    try:
        app.state.contenedor.verificar_base_datos()
        logger.info("Conexión a RDS verificada.")
    except Exception as error:
        # La API arranca igualmente; /health/db mostrará el problema.
        logger.warning(
            "No se pudo verificar RDS al arrancar (%s).",
            error.__class__.__name__,
        )

    yield

    await app.state.contenedor.demo_ejecutor.cerrar()


app = FastAPI(
    title="API Vehículo IoT",
    description=DESCRIPCION,
    version="1.0.0",
    openapi_tags=ETIQUETAS,
    lifespan=lifespan,
)


@app.exception_handler(ErrorAplicacion)
async def manejar_error_aplicacion(request: Request, error: ErrorAplicacion):
    if error.codigo_http >= 500:
        logger.error("%s %s -> %s", request.method, request.url.path,
                     error.codigo_http)

    return JSONResponse(
        status_code=error.codigo_http,
        content={"detail": error.mensaje},
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


for modulo in (sistema, vehiculos, comandos, estado, historial,
               movimientos, demos, ws):
    app.include_router(modulo.router)
