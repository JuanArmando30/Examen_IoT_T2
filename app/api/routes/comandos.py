from typing import List

from fastapi import APIRouter

from app.api.dependencies import (
    Administrador, ContenedorDep, IdComando, IdVehiculo, Operador,
)
from app.api.documentacion import BORRADO, ESCRITURA, LECTURA, TAG_COMANDOS
from app.models.schemas import (
    ComandoActualizar, ComandoCrear, ComandoOut, MensajeOut,
)

router = APIRouter(prefix="/vehiculos/{id_vehiculo}/comandos",
                   tags=[TAG_COMANDOS])


@router.get(
    "",
    summary="Catálogo de comandos del vehículo",
    response_model=List[ComandoOut],
    responses=LECTURA,
)
def listar_comandos(id_vehiculo: IdVehiculo, contenedor: ContenedorDep):
    """**Stored Procedures:** `sp_obtener_vehiculo` (existencia) y
    `sp_obtener_comandos_vehiculo`.

    Un vehículo existente sin comandos devuelve `[]` (200); un vehículo
    inexistente devuelve 404.
    """
    return contenedor.comandos.listar(id_vehiculo)


@router.post(
    "",
    summary="Crear un comando en el catálogo",
    status_code=201,
    response_model=ComandoOut,
    responses=ESCRITURA,
)
def crear_comando(
    id_vehiculo: IdVehiculo, cuerpo: ComandoCrear,
    contenedor: ContenedorDep, _rol: Operador,
):
    """Agrega un comando NUEVO al catálogo (no ejecuta ningún movimiento).

    Nombre y código deben ser únicos dentro del vehículo (409 si se repiten).

    **Stored Procedures:** `sp_crear_comando` y `sp_obtener_comandos_vehiculo`.
    """
    return contenedor.comandos.crear(
        id_vehiculo, cuerpo.nombre, cuerpo.codigo, cuerpo.descripcion,
    )


@router.post(
    "/{id_comando}/actualizar",
    summary="Actualizar un comando del catálogo",
    response_model=ComandoOut,
    responses=ESCRITURA,
)
def actualizar_comando(
    id_vehiculo: IdVehiculo, id_comando: IdComando,
    cuerpo: ComandoActualizar, contenedor: ContenedorDep, _rol: Operador,
):
    """**Stored Procedures:** `sp_actualizar_comando` y
    `sp_obtener_comandos_vehiculo`."""
    return contenedor.comandos.actualizar(
        id_vehiculo, id_comando, cuerpo.nombre, cuerpo.codigo,
        cuerpo.descripcion, cuerpo.activo,
    )


@router.post(
    "/{id_comando}/eliminar",
    summary="Eliminar un comando (solo administrador)",
    response_model=MensajeOut,
    responses=BORRADO,
)
def eliminar_comando(
    id_vehiculo: IdVehiculo, id_comando: IdComando,
    contenedor: ContenedorDep, _rol: Administrador,
):
    """Si el comando pertenece a una DEMO, responde 409.

    **Stored Procedures:** `sp_obtener_comandos_vehiculo` y
    `sp_eliminar_comando`.
    """
    contenedor.comandos.eliminar(id_vehiculo, id_comando)
    return {"mensaje": "Comando eliminado.", "id": id_comando}
