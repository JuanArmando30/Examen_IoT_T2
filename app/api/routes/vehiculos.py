from typing import List

from fastapi import APIRouter

from app.api.dependencies import (
    Administrador, ContenedorDep, IdVehiculo, Operador,
)
from app.api.documentacion import BORRADO, ESCRITURA, LECTURA, TAG_VEHICULOS
from app.core.exceptions import ConflictoNegocio
from app.models.schemas import (
    MensajeOut, VehiculoActualizar, VehiculoCrear, VehiculoDetalleOut,
    VehiculoOut,
)

router = APIRouter(prefix="/vehiculos", tags=[TAG_VEHICULOS])


@router.get(
    "",
    summary="Listar vehículos",
    response_model=List[VehiculoOut],
    responses=LECTURA,
)
def listar_vehiculos(contenedor: ContenedorDep):
    """**Stored Procedure:** `sp_obtener_vehiculos`."""
    return contenedor.vehiculos.listar()


@router.post(
    "",
    summary="Crear un vehículo",
    status_code=201,
    response_model=VehiculoOut,
    responses=ESCRITURA,
)
def crear_vehiculo(
    cuerpo: VehiculoCrear, contenedor: ContenedorDep, _rol: Operador,
):
    """**Stored Procedures:** `sp_crear_vehiculo` y `sp_obtener_vehiculo`.

    Requiere cabecera `X-API-Key` (operador o administrador).
    """
    return contenedor.vehiculos.crear(
        cuerpo.nombre, cuerpo.modelo, cuerpo.descripcion,
        cuerpo.microcontrolador,
    )


@router.get(
    "/{id_vehiculo}",
    summary="Detalle de un vehículo",
    response_model=VehiculoDetalleOut,
    responses=LECTURA,
)
def obtener_vehiculo(id_vehiculo: IdVehiculo, contenedor: ContenedorDep):
    """Devuelve el vehículo con su catálogo de comandos, su último estado
    y sus DEMO.

    **Stored Procedures:** `sp_obtener_vehiculo`,
    `sp_obtener_comandos_vehiculo`, `sp_obtener_estado`, `sp_obtener_demos`.
    """
    return contenedor.vehiculos.detalle(id_vehiculo)


@router.post(
    "/{id_vehiculo}/actualizar",
    summary="Actualizar un vehículo",
    response_model=VehiculoOut,
    responses=ESCRITURA,
)
def actualizar_vehiculo(
    id_vehiculo: IdVehiculo, cuerpo: VehiculoActualizar,
    contenedor: ContenedorDep, _rol: Operador,
):
    """Reemplaza los datos del vehículo (todos los campos).

    **Stored Procedures:** `sp_actualizar_vehiculo` y `sp_obtener_vehiculo`.
    """
    return contenedor.vehiculos.actualizar(
        id_vehiculo, cuerpo.nombre, cuerpo.modelo, cuerpo.descripcion,
        cuerpo.microcontrolador, cuerpo.activo,
    )


@router.post(
    "/{id_vehiculo}/eliminar",
    summary="Eliminar un vehículo (solo administrador)",
    response_model=MensajeOut,
    responses=BORRADO,
)
def eliminar_vehiculo(
    id_vehiculo: IdVehiculo, contenedor: ContenedorDep, _rol: Administrador,
):
    """Elimina el vehículo y, por cascada, sus comandos, estado, historial
    y DEMO.

    **Stored Procedures:** `sp_obtener_vehiculo` y `sp_eliminar_vehiculo`.
    """
    if contenedor.demo_ejecutor.esta_ejecutando(id_vehiculo):
        raise ConflictoNegocio(
            "El vehículo tiene una DEMO en ejecución. Cancélala primero."
        )

    contenedor.vehiculos.eliminar(id_vehiculo)
    return {"mensaje": "Vehículo eliminado.", "id": id_vehiculo}
