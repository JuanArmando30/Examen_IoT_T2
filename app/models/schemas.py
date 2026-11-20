"""Modelos de entrada y salida (validación + documentación Swagger)."""

from datetime import datetime
from typing import Any, Generic, List, Literal, Optional, TypeVar

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


# ===================== ADMINISTRACIÓN (Etapa 3) =====================

EstadoComercial = Literal["inventario", "vendida", "exhibicion", "baja"]
T = TypeVar("T")


class Pagina(BaseModel, Generic[T]):
    """Listado paginado: `total` es el número de resultados con esos filtros."""

    total: int
    limite: int
    desplazamiento: int
    elementos: List[T]


class ModeloCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    descripcion: Optional[str] = Field(default=None, max_length=255)
    microcontrolador: Optional[str] = Field(default=None, max_length=50)
    max_movimiento_ms: int = Field(default=3000, ge=100, le=60000,
                                   description="Tope de un movimiento individual (el firmware usa 3000).")
    max_paso_ms: int = Field(default=10000, ge=100, le=600000, description="Tope de un paso de DEMO.")
    max_pasos_demo: int = Field(default=50, ge=1, le=500)
    max_demo_ms: int = Field(default=300000, ge=1000, le=3600000, description="Tope de una DEMO completa.")

    @model_validator(mode="after")
    def _coherente(self):
        if self.max_demo_ms < self.max_paso_ms:
            raise ValueError("max_demo_ms no puede ser menor que max_paso_ms.")
        return self

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "nombre": "Excavadora X1", "descripcion": "Excavadora a escala con brazo y pala",
        "microcontrolador": "ESP32", "max_movimiento_ms": 3000, "max_paso_ms": 10000,
        "max_pasos_demo": 50, "max_demo_ms": 300000,
    }]})


class ModeloActualizar(ModeloCrear):
    activo: bool = True


class CapacidadGuardar(BaseModel):
    nombre: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_]+$")
    codigo: int = Field(ge=0, le=65535)
    descripcion: Optional[str] = Field(default=None, max_length=255)
    tipo: Literal["movimiento", "accesorio", "paro"] = "movimiento"
    permitido_invitado: bool = False

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "nombre": "AVANZAR", "codigo": 1, "tipo": "movimiento", "permitido_invitado": True,
    }]})


class UnidadCrear(BaseModel):
    id_modelo: int = Field(gt=0)
    nombre: str = Field(min_length=1, max_length=80)
    numero_serie: Optional[str] = Field(default=None, min_length=1, max_length=40,
                                        pattern=r"^[A-Za-z0-9._\-]+$")
    descripcion: Optional[str] = Field(default=None, max_length=255)
    estado_comercial: Literal["inventario", "exhibicion"] = "inventario"
    es_simulada: bool = Field(default=False, description="Unidad sin hardware, siempre mostrada como simulada.")

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "id_modelo": 1, "nombre": "Excavadora de pruebas B", "numero_serie": "SIM-0002",
        "estado_comercial": "inventario", "es_simulada": True,
    }]})


class UnidadActualizar(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    numero_serie: Optional[str] = Field(default=None, min_length=1, max_length=40,
                                        pattern=r"^[A-Za-z0-9._\-]+$")
    descripcion: Optional[str] = Field(default=None, max_length=255)
    estado_comercial: EstadoComercial
    activo: bool = True


class UsuarioCrear(BaseModel):
    correo: str = Field(min_length=3, max_length=254)
    nombre: str = Field(min_length=1, max_length=100)
    rol: Literal["admin", "usuario"] = "usuario"

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "correo": "cliente@ejemplo.com", "nombre": "Cliente de ejemplo", "rol": "usuario",
    }]})


class UsuarioActualizar(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    rol: Literal["admin", "usuario"]
    activo: bool = True


class AsignacionCrear(BaseModel):
    id_vehiculo: int = Field(gt=0)
    id_usuario: int = Field(gt=0)


class AsignacionFinalizar(BaseModel):
    motivo: Optional[str] = Field(default=None, max_length=30)
    estado_resultante: Literal["inventario", "exhibicion", "baja"] = "inventario"


class ModeloOut(BaseModel):
    id_modelo: int
    nombre: str
    descripcion: Optional[str] = None
    microcontrolador: Optional[str] = None
    max_movimiento_ms: int
    max_paso_ms: int
    max_pasos_demo: int
    max_demo_ms: int
    activo: bool
    fecha_registro: Optional[datetime] = None
    unidades: int = 0
    capacidades: int = 0


class CapacidadOut(BaseModel):
    id_modelo_comando: int
    id_modelo: int
    nombre: str
    codigo: int
    descripcion: Optional[str] = None
    tipo: str
    permitido_invitado: bool


class UnidadOut(BaseModel):
    id_vehiculo: int
    nombre: str
    numero_serie: Optional[str] = None
    estado_comercial: str
    es_simulada: bool
    activo: bool
    descripcion: Optional[str] = None
    microcontrolador: Optional[str] = None
    fecha_registro: Optional[datetime] = None
    id_modelo: Optional[int] = None
    modelo: Optional[str] = None
    id_asignacion: Optional[int] = None
    id_propietario: Optional[int] = None
    propietario: Optional[str] = None
    correo_propietario: Optional[str] = None
    asignada_desde: Optional[datetime] = None
    conectado: Optional[bool] = None
    fecha_actualizacion: Optional[datetime] = None


class UsuarioOut(BaseModel):
    id_usuario: int
    correo: str
    nombre: str
    rol: str
    activo: bool
    creado_en: Optional[datetime] = None
    ultimo_acceso: Optional[datetime] = None
    tiene_contrasena: bool
    unidades: int = 0


class AsignacionOut(BaseModel):
    id_asignacion: int
    id_vehiculo: int
    unidad: str
    numero_serie: Optional[str] = None
    id_usuario: int
    usuario: str
    correo: str
    asignado_por: Optional[int] = None
    asignado_por_nombre: Optional[str] = None
    desde: datetime
    hasta: Optional[datetime] = None
    motivo_fin: Optional[str] = None
    vigente: bool


class AuditoriaOut(BaseModel):
    id_auditoria: int
    ocurrido_en: datetime
    id_usuario: Optional[int] = None
    usuario: Optional[str] = None
    rol_actor: str
    accion: str
    recurso_tipo: Optional[str] = None
    recurso_id: Optional[str] = None
    resultado: str
    detalle: Optional[Any] = None


class MetricasOut(BaseModel):
    unidades: int
    unidades_inventario: int
    unidades_vendidas: int
    unidades_exhibicion: int
    unidades_baja: int
    unidades_simuladas: int
    modelos_activos: int
    clientes_activos: int
    administradores_activos: int
    asignaciones_vigentes: int
    demos_fabrica: int
    demos_privadas: int
    reservas_vigentes: int
    movimientos_24h: int
    movimientos_7d: int
    movimientos_total: int
    ultimo_movimiento: Optional[datetime] = None
    generado_en: datetime


# ===================== SESIÓN (Etapa 4) =====================


class LoginSolicitud(BaseModel):
    correo: str = Field(min_length=3, max_length=254)
    contrasena: str = Field(min_length=1, max_length=128, repr=False)

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "correo": "cliente@ejemplo.com", "contrasena": "********",
    }]})


class RenovarSolicitud(BaseModel):
    token_renovacion: str = Field(min_length=16, max_length=128, repr=False)


class RestablecerSolicitud(BaseModel):
    correo: str = Field(min_length=3, max_length=254)
    codigo: str = Field(min_length=10, max_length=16, repr=False,
                        description="Código XXXXX-XXXXX que entregó el administrador.")
    contrasena_nueva: str = Field(min_length=10, max_length=128, repr=False)


class CambiarContrasenaSolicitud(BaseModel):
    contrasena_actual: str = Field(min_length=1, max_length=128, repr=False)
    contrasena_nueva: str = Field(min_length=10, max_length=128, repr=False)


class SoporteOtorgar(BaseModel):
    horas: int = Field(default=24, ge=1, le=72, description="Vigencia de la autorización (1–72 h).")
    motivo: Optional[str] = Field(default=None, max_length=255)
    id_administrador: Optional[int] = Field(
        default=None, gt=0,
        description="Solo ese administrador; vacío = cualquier administrador activo.")


class UsuarioSesionOut(BaseModel):
    id_usuario: int
    correo: str
    nombre: str
    rol: Literal["admin", "usuario"]
    debe_cambiar_contrasena: bool = False


class SesionOut(BaseModel):
    token_acceso: str
    tipo: Literal["Bearer"] = "Bearer"
    expira_en: int = Field(description="Segundos de vigencia del token de acceso.")
    acceso_expira: datetime
    token_renovacion: str = Field(description="Guárdalo con cuidado: rota en cada /auth/renovar.")
    renovacion_expira: datetime
    usuario: UsuarioSesionOut


class CodigoRestablecimientoOut(BaseModel):
    id_usuario: int
    correo: str
    codigo: str = Field(description="Se muestra UNA sola vez; entrégalo al usuario por un canal seguro.")
    expira_en: datetime
    minutos: int


class MiVehiculoOut(BaseModel):
    id_vehiculo: int
    nombre: str
    numero_serie: Optional[str] = None
    estado_comercial: str
    es_simulada: bool
    activo: bool
    id_modelo: Optional[int] = None
    modelo: Optional[str] = None
    id_asignacion: int
    asignada_desde: datetime
    conectado: Optional[bool] = None
    fecha_actualizacion: Optional[datetime] = None


class SoporteOut(BaseModel):
    id_autorizacion: int
    id_vehiculo: int
    otorgada_por: int
    otorgada_a: Optional[int] = None
    administrador: Optional[str] = None
    motivo: Optional[str] = None
    creada_en: datetime
    expira_en: datetime
    revocada_en: Optional[datetime] = None
    vigente: bool


class SoporteRevocadoOut(BaseModel):
    id_vehiculo: int
    revocadas: int


# ================== DEMO privadas y editor (Etapa 6) ==================


class LimitesOut(BaseModel):
    """Límites de seguridad de la unidad (de su modelo)."""

    id_vehiculo: int
    id_modelo: Optional[int] = None
    modelo: Optional[str] = None
    estado_comercial: Optional[str] = None
    max_movimiento_ms: int
    max_paso_ms: int
    max_pasos_demo: int
    max_demo_ms: int


class DemoPrivadaCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    descripcion: Optional[str] = Field(default=None, max_length=255)

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "nombre": "Mi rutina de exhibición", "descripcion": "Avanza, gira y saluda con la pala",
    }]})


class DemoPrivadaActualizar(DemoPrivadaCrear):
    activo: bool = True


class PasoDemo(BaseModel):
    """Un paso del editor. El orden es la posición en la lista."""

    id_comando: int = Field(gt=0)
    duracion_ms: int = Field(ge=1, le=600000)
    pausa_ms: int = Field(default=0, ge=0, le=600000)


class PasosDemoGuardar(BaseModel):
    pasos: List[PasoDemo] = Field(max_length=500)

    model_config = ConfigDict(json_schema_extra={"examples": [{"pasos": [
        {"id_comando": 1, "duracion_ms": 1500, "pausa_ms": 300},
        {"id_comando": 3, "duracion_ms": 800, "pausa_ms": 0},
    ]}]})


class DemoResumenOut(BaseModel):
    id_demo: int
    id_vehiculo: int
    nombre: str
    descripcion: Optional[str] = None
    activo: bool
    ambito: Literal["fabrica", "privada"]
    propia: bool
    pasos: int
    duracion_total_ms: int


class DemoDetalleOut(DemoResumenOut):
    movimientos: List[MovimientoDemoOut]


# ================== INVITADOS (Etapa 7) ==================


class ReservaSolicitud(BaseModel):
    id_vehiculo: int = Field(gt=0)


class ExhibicionCambiar(BaseModel):
    abierta: bool
    horas: int = Field(default=2, ge=1, le=8, description="Cuánto tiempo queda abierta (1–8 h); se cierra sola.")


class UnidadCatalogoOut(BaseModel):
    id_vehiculo: int
    nombre: str
    descripcion: Optional[str] = None
    es_simulada: bool
    modelo: Optional[str] = None
    modelo_descripcion: Optional[str] = None
    microcontrolador: Optional[str] = None
    conectado: Optional[bool] = None
    exhibicion_abierta: bool
    disponible: bool
    segundos_reserva: int
    minutos_reserva: int


class ComandoInvitadoOut(BaseModel):
    id_comando: int
    nombre: str
    codigo: int
    tipo: Optional[str] = None


class DemoInvitadoOut(BaseModel):
    id_demo: int
    nombre: str
    descripcion: Optional[str] = None
    pasos: int
    duracion_total_ms: int


class ReservaOut(BaseModel):
    id_reserva: int
    id_vehiculo: int
    expira_en: datetime
    segundos_restantes: int
    latido_max_s: int
    comandos: List[ComandoInvitadoOut]
    demos: List[DemoInvitadoOut]


class ReservaCreadaOut(ReservaOut):
    token_invitado: str = Field(description="Guárdalo solo en la pestaña (memoria o sessionStorage, nunca localStorage); se manda en la cabecera X-Invitado.")


class LatidoOut(BaseModel):
    segundos_restantes: int
    en_demo: bool


class ReservaVigenteOut(BaseModel):
    id_reserva: int
    expira_en: datetime
    segundos_restantes: int


class ExhibicionOut(BaseModel):
    id_vehiculo: int
    abierta: bool
    abierta_hasta: Optional[datetime] = None
    reserva: Optional[ReservaVigenteOut] = None


# ================== Tiempo real y dispositivo (Etapa 8) ==================


class TicketSolicitud(BaseModel):
    id_vehiculo: int = Field(gt=0)


class SujetoOut(BaseModel):
    tipo: str
    rol: Optional[str] = None


class TicketOut(BaseModel):
    ticket: str
    expira_en_s: int
    sujeto: SujetoOut


class CredencialDispositivoOut(BaseModel):
    id_credencial: int
    creada_en: Optional[datetime] = None
    ultimo_uso: Optional[datetime] = None
    vigente: bool


class DispositivoOut(BaseModel):
    id_vehiculo: int
    conectado: bool = Field(description="El ESP32 está conectado ahora mismo con su credencial.")
    credencial: Optional[CredencialDispositivoOut] = None
    ws_abierto: bool
    revocadas: Optional[int] = None


class SecretoDispositivoOut(BaseModel):
    id_vehiculo: int
    id_credencial: int
    secreto: str = Field(description="Se muestra UNA sola vez: va en secretos.h del firmware.")
