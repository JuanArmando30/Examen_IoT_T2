"""Modelos de entrada y salida (validación + documentación Swagger)."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ============================ ENTRADA ============================


class VehiculoCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    modelo: Optional[str] = Field(default=None, max_length=80)
    descripcion: Optional[str] = Field(default=None, max_length=255)
    microcontrolador: Optional[str] = Field(default=None, max_length=50)

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "nombre": "Retroexcavadora IoT",
        "modelo": "Modelo Y",
        "descripcion": "Vehículo de prueba controlado por ESP32",
        "microcontrolador": "ESP32",
    }]})


class VehiculoActualizar(VehiculoCrear):
    activo: bool = True


class ComandoCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    codigo: int = Field(ge=0, le=65535)
    descripcion: Optional[str] = Field(default=None, max_length=255)

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "nombre": "LUCES",
        "codigo": 10,
        "descripcion": "Encender las luces",
    }]})


class ComandoActualizar(ComandoCrear):
    activo: bool = True


class MovimientoSolicitud(BaseModel):
    """Movimiento individual: indica id_comando O codigo (uno solo)."""

    id_comando: Optional[int] = Field(default=None, gt=0)
    codigo: Optional[int] = Field(default=None, ge=0, le=65535)
    origen: str = Field(
        default="API", min_length=1, max_length=30,
        pattern=r"^[A-Za-z0-9_\-]+$",
        description="Quién originó el movimiento (se guarda en el historial).",
    )

    @model_validator(mode="after")
    def _exactamente_uno(self):
        if (self.id_comando is None) == (self.codigo is None):
            raise ValueError("Indica exactamente uno: id_comando o codigo.")
        return self

    model_config = ConfigDict(json_schema_extra={"examples": [
        {"id_comando": 1, "origen": "THUNDER_CLIENT"},
    ]})


class EstadoActualizar(BaseModel):
    conectado: bool
    id_comando: Optional[int] = Field(
        default=None, gt=0,
        description="Si se omite, se conserva el último comando.",
    )


class DemoCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    descripcion: Optional[str] = Field(default=None, max_length=255)


class DemoActualizar(DemoCrear):
    activo: bool = True


class MovimientoDemoCrear(BaseModel):
    id_comando: int = Field(gt=0)
    orden: int = Field(ge=1, le=10000)
    duracion_ms: int = Field(ge=1, le=600000)
    pausa_ms: int = Field(default=0, ge=0, le=600000)

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "id_comando": 1, "orden": 9, "duracion_ms": 1000, "pausa_ms": 200,
    }]})


class MovimientoDemoActualizar(MovimientoDemoCrear):
    pass


# ============================ SALIDA ============================


class ComandoOut(BaseModel):
    id_comando: int
    id_vehiculo: int
    nombre: str
    codigo: int
    descripcion: Optional[str] = None
    activo: bool


class EstadoOut(BaseModel):
    id_vehiculo: int
    vehiculo: str
    id_comando: Optional[int] = None
    comando: Optional[str] = None
    codigo: Optional[int] = None
    conectado: bool
    fecha_actualizacion: Optional[datetime] = None


class DemoOut(BaseModel):
    id_demo: int
    id_vehiculo: int
    nombre: str
    descripcion: Optional[str] = None
    activo: bool


class VehiculoOut(BaseModel):
    id_vehiculo: int
    nombre: str
    modelo: Optional[str] = None
    descripcion: Optional[str] = None
    microcontrolador: Optional[str] = None
    fecha_registro: Optional[datetime] = None
    activo: bool


class VehiculoDetalleOut(VehiculoOut):
    comandos: List[ComandoOut]
    estado: Optional[EstadoOut] = None
    demos: List[DemoOut]


class HistorialItemOut(BaseModel):
    id_historial: int
    id_vehiculo: int
    comando: Optional[str] = None
    codigo: Optional[int] = None
    fecha_hora: Optional[datetime] = None
    origen: str


class HistorialOut(BaseModel):
    id_vehiculo: int
    limite: int
    total_devueltos: int
    movimientos: List[HistorialItemOut]


class MovimientoRegistradoOut(BaseModel):
    id_vehiculo: int
    id_comando: int
    comando: str
    codigo: int
    origen: str
    conectado: bool
    fecha_actualizacion: Optional[datetime] = None
    clientes_notificados: int = 0
    mensaje: str


class MovimientoDemoOut(BaseModel):
    id_demo_movimiento: int
    orden: int
    id_comando: int
    comando: str
    codigo: int
    duracion_ms: int
    pausa_ms: int


class DemoIniciadaOut(BaseModel):
    id_vehiculo: int
    id_demo: int
    nombre: str
    total_movimientos: int
    duracion_estimada_ms: int
    clientes_websocket: int
    mensaje: str


class DemoCanceladaOut(BaseModel):
    id_vehiculo: int
    id_demo: int
    movimientos_emitidos: int
    mensaje: str


class DemoEjecucionOut(BaseModel):
    en_ejecucion: bool
    id_demo: Optional[int] = None
    nombre: Optional[str] = None
    movimientos_emitidos: Optional[int] = None
    total_movimientos: Optional[int] = None
    orden_actual: Optional[int] = None
    iniciada_en: Optional[datetime] = None
    cancelacion_solicitada: Optional[bool] = None


class MensajeOut(BaseModel):
    mensaje: str
    id: Optional[int] = None


class ErrorOut(BaseModel):
    detail: str


class SaludOut(BaseModel):
    estado: str
