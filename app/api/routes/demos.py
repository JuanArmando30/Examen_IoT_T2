from typing import List

from fastapi import APIRouter

from app.api.dependencies import (
    Administrador, ContenedorDep, IdDemo, IdMovimiento, IdVehiculo, Operador,
)
from app.api.documentacion import (
    BORRADO, ESCRITURA, LECTURA, TAG_DEMO, TAG_MOV_DEMO,
)
from app.core.exceptions import ConflictoNegocio
from app.models.schemas import (
    DemoActualizar, DemoCanceladaOut, DemoCrear, DemoEjecucionOut,
    DemoIniciadaOut, DemoOut, MensajeOut, MovimientoDemoActualizar,
    MovimientoDemoCrear, MovimientoDemoOut,
)

router = APIRouter(prefix="/vehiculos/{id_vehiculo}/demos")


# ============================ DEMO ============================


@router.get(
    "", tags=[TAG_DEMO],
    summary="Listar las DEMO del vehículo",
    response_model=List[DemoOut], responses=LECTURA,
)
def listar_demos(id_vehiculo: IdVehiculo, contenedor: ContenedorDep):
    """**Stored Procedures:** `sp_obtener_vehiculo` y `sp_obtener_demos`."""
    return contenedor.demos.listar(id_vehiculo)


@router.post(
    "", tags=[TAG_DEMO], status_code=201,
    summary="Crear una DEMO",
    response_model=DemoOut, responses=ESCRITURA,
)
def crear_demo(
    id_vehiculo: IdVehiculo, cuerpo: DemoCrear,
    contenedor: ContenedorDep, _rol: Operador,
):
    """Crea la DEMO vacía; sus movimientos se agregan con
    `POST .../demos/{id_demo}/movimientos`.

    **Stored Procedures:** `sp_crear_demo` y `sp_obtener_demos`.
    """
    return contenedor.demos.crear(
        id_vehiculo, cuerpo.nombre, cuerpo.descripcion
    )


@router.get(
    "/ejecucion", tags=[TAG_DEMO],
    summary="¿Hay una DEMO en ejecución?",
    response_model=DemoEjecucionOut, responses=LECTURA,
)
def estado_ejecucion(id_vehiculo: IdVehiculo, contenedor: ContenedorDep):
    """Estado en memoria de la ejecución (no consulta RDS salvo la
    existencia del vehículo: `sp_obtener_vehiculo`)."""
    contenedor.vehiculos.obtener_o_fallar(id_vehiculo)
    return contenedor.demo_ejecutor.estado(id_vehiculo)


@router.post(
    "/cancelar", tags=[TAG_DEMO],
    summary="Cancelar la DEMO en ejecución",
    response_model=DemoCanceladaOut, responses=ESCRITURA,
)
async def cancelar_demo(
    id_vehiculo: IdVehiculo, contenedor: ContenedorDep, _rol: Operador,
):
    """Suspende **inmediatamente** la emisión de movimientos posteriores,
    deja el estado en `DETENER` (si el vehículo tiene ese comando) y
    notifica `demo_cancelada` por WebSocket. 409 si no hay DEMO en curso.

    **Stored Procedures:** `sp_obtener_comandos_vehiculo` y
    `sp_actualizar_estado` (no usa `sp_registrar_historial`).
    """
    return await contenedor.demo_ejecutor.cancelar(id_vehiculo)


@router.post(
    "/{id_demo}/actualizar", tags=[TAG_DEMO],
    summary="Actualizar una DEMO",
    response_model=DemoOut, responses=ESCRITURA,
)
def actualizar_demo(
    id_vehiculo: IdVehiculo, id_demo: IdDemo, cuerpo: DemoActualizar,
    contenedor: ContenedorDep, _rol: Operador,
):
    """**Stored Procedures:** `sp_actualizar_demo` y `sp_obtener_demos`."""
    return contenedor.demos.actualizar(
        id_vehiculo, id_demo, cuerpo.nombre, cuerpo.descripcion, cuerpo.activo
    )


@router.post(
    "/{id_demo}/eliminar", tags=[TAG_DEMO],
    summary="Eliminar una DEMO (solo administrador)",
    response_model=MensajeOut, responses=BORRADO,
)
def eliminar_demo(
    id_vehiculo: IdVehiculo, id_demo: IdDemo,
    contenedor: ContenedorDep, _rol: Administrador,
):
    """Elimina la DEMO y, por cascada, sus movimientos.

    **Stored Procedures:** `sp_obtener_demos` y `sp_eliminar_demo`.
    """
    ejecucion = contenedor.demo_ejecutor.estado(id_vehiculo)

    if ejecucion["en_ejecucion"] and ejecucion["id_demo"] == id_demo:
        raise ConflictoNegocio("La DEMO se está ejecutando. Cancélala antes.")

    contenedor.demos.eliminar(id_vehiculo, id_demo)
    return {"mensaje": "DEMO eliminada.", "id": id_demo}


@router.post(
    "/{id_demo}/iniciar", tags=[TAG_DEMO], status_code=202,
    summary="Iniciar una DEMO (se transmite por WebSocket)",
    response_model=DemoIniciadaOut, responses=ESCRITURA,
)
async def iniciar_demo(
    id_vehiculo: IdVehiculo, id_demo: IdDemo,
    contenedor: ContenedorDep, _rol: Operador,
):
    """Responde **202 Accepted** de inmediato; la secuencia corre en segundo
    plano y se transmite por `ws://localhost:8000/ws/vehiculos/{id_vehiculo}`:
    `demo_iniciada` -> N × `demo_movimiento` (respetando `duracion_ms` y
    `pausa_ms`) -> `demo_finalizada`.

    - Los movimientos se leen de RDS (no hay secuencia fija en el código).
    - Actualiza el último comando con `sp_actualizar_estado`.
    - **NO** llama a `sp_registrar_historial`: la DEMO nunca llega al
      historial.
    - 409 si la DEMO está inactiva, no tiene movimientos o el vehículo ya
      ejecuta otra DEMO.

    **Stored Procedures:** `sp_obtener_vehiculo`, `sp_obtener_demos`,
    `sp_obtener_movimientos_demo`, `sp_obtener_comandos_vehiculo`,
    `sp_obtener_estado`, `sp_actualizar_estado`.
    """
    return await contenedor.demo_ejecutor.iniciar(id_vehiculo, id_demo)


# ====================== MOVIMIENTOS DE DEMO ======================


@router.get(
    "/{id_demo}/movimientos", tags=[TAG_MOV_DEMO],
    summary="Movimientos ordenados de una DEMO",
    response_model=List[MovimientoDemoOut], responses=LECTURA,
)
def listar_movimientos(
    id_vehiculo: IdVehiculo, id_demo: IdDemo, contenedor: ContenedorDep,
):
    """**Stored Procedures:** `sp_obtener_demos` (pertenencia) y
    `sp_obtener_movimientos_demo` (ordenados por `orden`)."""
    return contenedor.demos.movimientos(id_vehiculo, id_demo)


@router.post(
    "/{id_demo}/movimientos", tags=[TAG_MOV_DEMO], status_code=201,
    summary="Agregar un movimiento a la DEMO",
    response_model=MovimientoDemoOut, responses=ESCRITURA,
)
def agregar_movimiento(
    id_vehiculo: IdVehiculo, id_demo: IdDemo, cuerpo: MovimientoDemoCrear,
    contenedor: ContenedorDep, _rol: Operador,
):
    """El comando debe estar activo y pertenecer al catálogo del vehículo;
    `orden` no puede repetirse dentro de la DEMO (409).

    **Stored Procedures:** `sp_agregar_movimiento_demo` y
    `sp_obtener_movimientos_demo`.
    """
    return contenedor.demos.agregar_movimiento(
        id_vehiculo, id_demo, cuerpo.id_comando, cuerpo.orden,
        cuerpo.duracion_ms, cuerpo.pausa_ms,
    )


@router.post(
    "/{id_demo}/movimientos/{id_movimiento}/actualizar",
    tags=[TAG_MOV_DEMO],
    summary="Actualizar un movimiento de la DEMO",
    response_model=MovimientoDemoOut, responses=ESCRITURA,
)
def actualizar_movimiento(
    id_vehiculo: IdVehiculo, id_demo: IdDemo, id_movimiento: IdMovimiento,
    cuerpo: MovimientoDemoActualizar,
    contenedor: ContenedorDep, _rol: Operador,
):
    """**Stored Procedures:** `sp_actualizar_movimiento_demo` y
    `sp_obtener_movimientos_demo`."""
    return contenedor.demos.actualizar_movimiento(
        id_vehiculo, id_demo, id_movimiento, cuerpo.id_comando, cuerpo.orden,
        cuerpo.duracion_ms, cuerpo.pausa_ms,
    )


@router.post(
    "/{id_demo}/movimientos/{id_movimiento}/eliminar",
    tags=[TAG_MOV_DEMO],
    summary="Eliminar un movimiento de la DEMO (solo administrador)",
    response_model=MensajeOut, responses=BORRADO,
)
def eliminar_movimiento(
    id_vehiculo: IdVehiculo, id_demo: IdDemo, id_movimiento: IdMovimiento,
    contenedor: ContenedorDep, _rol: Administrador,
):
    """**Stored Procedures:** `sp_obtener_movimientos_demo` y
    `sp_eliminar_movimiento_demo`."""
    contenedor.demos.eliminar_movimiento(id_vehiculo, id_demo, id_movimiento)
    return {"mensaje": "Movimiento eliminado.", "id": id_movimiento}
