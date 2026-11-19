"""ADMINISTRACIÓN (Etapas 3–4): inventario de la empresa.

Todas las rutas exigen al administrador (token de un usuario con rol admin
o, en transición, la clave X-API-Key de administrador) y responden 503 si
la base aún no tiene las migraciones V001–V009. Convención de la API existente:
GET consulta y POST …/actualizar, POST …/baja, POST …/finalizar escriben.
El administrador gestiona el inventario; NO obtiene aquí control de las
unidades vendidas (eso exigirá la autorización de soporte del comprador).
"""

from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Query, Response

from app.api.dependencies import (
    ActorAdmin, ContenedorDep, IdAsignacion, IdModelo, IdUsuario, IdVehiculo,
)
from app.api.documentacion import ADMIN_ESCRITURA, ADMIN_LECTURA, TAG_ADMIN
from app.models.schemas import (
    AsignacionCrear, AsignacionFinalizar, AsignacionOut, AuditoriaOut,
    CapacidadGuardar, CodigoRestablecimientoOut, CapacidadOut, EstadoComercial, MensajeOut, MetricasOut,
    ModeloActualizar, ModeloCrear, ModeloOut, Pagina, UnidadActualizar,
    UnidadCrear, UnidadOut, UsuarioActualizar, UsuarioCrear, UsuarioOut,
)

router = APIRouter(prefix="/admin", tags=[TAG_ADMIN])

Limite = Query(50, ge=1, le=200, description="Máximo de resultados por página")
Desplazamiento = Query(0, ge=0, le=1_000_000, description="Resultados que se saltan")


# ----------------------------------------------------------------- Métricas

@router.get("/metricas", summary="Métricas del panel de administración",
            response_model=MetricasOut, responses=ADMIN_LECTURA)
def metricas(contenedor: ContenedorDep, _actor: ActorAdmin):
    """Conteos reales de RDS: unidades por estado comercial, clientes,
    asignaciones vigentes, DEMO, reservas y movimientos (24 h, 7 días, total).

    **SP:** `sp_metricas_admin`."""
    return contenedor.metricas.obtener()


# ----------------------------------------------------------------- Modelos

@router.get("/modelos", summary="Listar modelos", response_model=List[ModeloOut], responses=ADMIN_LECTURA)
def listar_modelos(contenedor: ContenedorDep, _actor: ActorAdmin):
    """**SP:** `sp_listar_modelos`."""
    return contenedor.modelos.listar()


@router.post("/modelos", summary="Crear un modelo", status_code=201,
             response_model=ModeloOut, responses=ADMIN_ESCRITURA)
def crear_modelo(cuerpo: ModeloCrear, contenedor: ContenedorDep, actor: ActorAdmin):
    """Límites de seguridad física: duración máxima de un movimiento
    individual, de un paso y de una DEMO completa, y número de pasos.

    **SP:** `sp_crear_modelo`, `sp_obtener_modelo`, `sp_registrar_auditoria`."""
    return contenedor.modelos.crear(actor, cuerpo)


@router.get("/modelos/{id_modelo}", summary="Detalle de un modelo",
            response_model=ModeloOut, responses=ADMIN_LECTURA)
def obtener_modelo(id_modelo: IdModelo, contenedor: ContenedorDep, _actor: ActorAdmin):
    """**SP:** `sp_obtener_modelo`."""
    return contenedor.modelos.obtener_o_fallar(id_modelo)


@router.post("/modelos/{id_modelo}/actualizar", summary="Actualizar un modelo",
             response_model=ModeloOut, responses=ADMIN_ESCRITURA)
def actualizar_modelo(id_modelo: IdModelo, cuerpo: ModeloActualizar,
                      contenedor: ContenedorDep, actor: ActorAdmin):
    """**SP:** `sp_actualizar_modelo`, `sp_obtener_modelo`, `sp_registrar_auditoria`."""
    return contenedor.modelos.actualizar(actor, id_modelo, cuerpo)


@router.get("/modelos/{id_modelo}/capacidades", summary="Capacidades (comandos) del modelo",
            response_model=List[CapacidadOut], responses=ADMIN_LECTURA)
def listar_capacidades(id_modelo: IdModelo, contenedor: ContenedorDep, _actor: ActorAdmin):
    """Comandos que el hardware de ese modelo realmente ejecuta. Una unidad
    nueva nace con este catálogo.

    **SP:** `sp_listar_capacidades`."""
    return contenedor.modelos.capacidades(id_modelo)


@router.post("/modelos/{id_modelo}/capacidades", summary="Crear o actualizar una capacidad",
             response_model=CapacidadOut, responses=ADMIN_ESCRITURA)
def guardar_capacidad(id_modelo: IdModelo, cuerpo: CapacidadGuardar,
                      contenedor: ContenedorDep, actor: ActorAdmin):
    """Identificada por el código. La capacidad de paro siempre queda
    disponible para invitados (DETENER nunca se restringe).

    **SP:** `sp_guardar_capacidad`, `sp_listar_capacidades`, `sp_registrar_auditoria`."""
    return contenedor.modelos.guardar_capacidad(actor, id_modelo, cuerpo)


@router.post("/modelos/{id_modelo}/capacidades/{codigo}/eliminar", summary="Eliminar una capacidad",
             response_model=MensajeOut, responses=ADMIN_ESCRITURA)
def eliminar_capacidad(id_modelo: IdModelo, codigo: int, contenedor: ContenedorDep, actor: ActorAdmin):
    """No se puede eliminar la capacidad de paro (DETENER). Las unidades ya
    creadas conservan su catálogo.

    **SP:** `sp_eliminar_capacidad`, `sp_registrar_auditoria`."""
    contenedor.modelos.eliminar_capacidad(actor, id_modelo, codigo)
    return {"mensaje": "Capacidad eliminada.", "id": codigo}


# ----------------------------------------------------------------- Unidades

@router.get("/unidades", summary="Inventario de unidades", response_model=Pagina[UnidadOut],
            responses=ADMIN_LECTURA)
def listar_unidades(contenedor: ContenedorDep, _actor: ActorAdmin,
                    estado: Optional[EstadoComercial] = None,
                    id_modelo: Optional[int] = Query(None, gt=0),
                    q: Optional[str] = Query(None, max_length=80, description="Busca en nombre y número de serie"),
                    limite: int = Limite, desplazamiento: int = Desplazamiento):
    """Unidades físicas con su modelo, comprador vigente y último estado.

    **SP:** `sp_listar_unidades`."""
    return contenedor.unidades.listar(estado, id_modelo, q, limite, desplazamiento)


@router.post("/unidades", summary="Registrar una unidad", status_code=201,
             response_model=UnidadOut, responses=ADMIN_ESCRITURA)
def crear_unidad(cuerpo: UnidadCrear, contenedor: ContenedorDep, actor: ActorAdmin):
    """La unidad nace en inventario o exhibición, con el catálogo de comandos
    de su modelo (en una sola transacción). `es_simulada` marca unidades sin
    hardware, que la interfaz siempre muestra como simuladas.

    **SP:** `sp_crear_unidad`, `sp_obtener_unidad`, `sp_registrar_auditoria`."""
    return contenedor.unidades.crear(actor, cuerpo)


@router.get("/unidades/{id_vehiculo}", summary="Detalle de una unidad",
            response_model=UnidadOut, responses=ADMIN_LECTURA)
def obtener_unidad(id_vehiculo: IdVehiculo, contenedor: ContenedorDep, _actor: ActorAdmin):
    """**SP:** `sp_obtener_unidad`."""
    return contenedor.unidades.obtener_o_fallar(id_vehiculo)


@router.post("/unidades/{id_vehiculo}/actualizar", summary="Actualizar una unidad",
             response_model=UnidadOut, responses=ADMIN_ESCRITURA)
def actualizar_unidad(id_vehiculo: IdVehiculo, cuerpo: UnidadActualizar,
                      contenedor: ContenedorDep, actor: ActorAdmin):
    """El estado «vendida» solo cambia con las asignaciones y la baja tiene
    su propia ruta.

    **SP:** `sp_actualizar_unidad`, `sp_obtener_unidad`, `sp_registrar_auditoria`."""
    return contenedor.unidades.actualizar(actor, id_vehiculo, cuerpo)


@router.post("/unidades/{id_vehiculo}/baja", summary="Dar de baja una unidad",
             response_model=UnidadOut, responses=ADMIN_ESCRITURA)
def baja_unidad(id_vehiculo: IdVehiculo, contenedor: ContenedorDep, actor: ActorAdmin):
    """En lugar de borrarla: conserva su historial. Exige que no tenga
    comprador, reserva ni DEMO en curso.

    **SP:** `sp_baja_unidad`, `sp_obtener_unidad`, `sp_registrar_auditoria`."""
    return contenedor.unidades.baja(actor, id_vehiculo)


# ----------------------------------------------------------------- Usuarios

@router.get("/usuarios", summary="Clientes y administradores", response_model=Pagina[UsuarioOut],
            responses=ADMIN_LECTURA)
def listar_usuarios(contenedor: ContenedorDep, _actor: ActorAdmin,
                    rol: Optional[Literal["admin", "usuario"]] = None,
                    activo: Optional[bool] = None,
                    q: Optional[str] = Query(None, max_length=100, description="Busca en nombre y correo"),
                    limite: int = Limite, desplazamiento: int = Desplazamiento):
    """Nunca devuelve contraseñas ni hashes.

    **SP:** `sp_listar_usuarios`."""
    return contenedor.usuarios.listar(rol, activo, q, limite, desplazamiento)


@router.post("/usuarios", summary="Registrar un usuario", status_code=201,
             response_model=UsuarioOut, responses=ADMIN_ESCRITURA)
def crear_usuario(cuerpo: UsuarioCrear, contenedor: ContenedorDep, actor: ActorAdmin):
    """Se crea sin contraseña; en la Etapa 4 el administrador le generará un
    código de un solo uso para que la defina.

    **SP:** `sp_crear_usuario`, `sp_obtener_usuario`, `sp_registrar_auditoria`."""
    return contenedor.usuarios.crear(actor, cuerpo)


@router.get("/usuarios/{id_usuario}", summary="Detalle de un usuario",
            response_model=UsuarioOut, responses=ADMIN_LECTURA)
def obtener_usuario(id_usuario: IdUsuario, contenedor: ContenedorDep, _actor: ActorAdmin):
    """**SP:** `sp_obtener_usuario`."""
    return contenedor.usuarios.obtener_o_fallar(id_usuario)


@router.post("/usuarios/{id_usuario}/actualizar", summary="Actualizar un usuario (nombre, rol, activo)",
             response_model=UsuarioOut, responses=ADMIN_ESCRITURA)
def actualizar_usuario(id_usuario: IdUsuario, cuerpo: UsuarioActualizar,
                       contenedor: ContenedorDep, actor: ActorAdmin):
    """No permite dejar el sistema sin administradores activos ni cambiar el
    rol de un cliente con unidades. Desactivar revoca sus sesiones. Los
    cambios de rol quedan en la auditoría.

    **SP:** `sp_actualizar_usuario`, `sp_obtener_usuario`, `sp_registrar_auditoria`."""
    return contenedor.usuarios.actualizar(actor, id_usuario, cuerpo)


@router.post("/usuarios/{id_usuario}/codigo-restablecimiento", status_code=201,
             summary="Generar un código de restablecimiento (un solo uso)",
             response_model=CodigoRestablecimientoOut, responses=ADMIN_ESCRITURA)
def generar_codigo(id_usuario: IdUsuario, contenedor: ContenedorDep, actor: ActorAdmin,
                   response: Response):
    """Para dar la primera contraseña a un cliente nuevo o cuando la olvidó.
    El código se muestra **una sola vez** (en la base solo queda su HMAC),
    caduca en 30 min, admite 5 intentos e invalida los códigos anteriores.
    Requiere la migración V010 y TOKEN_SECRETO.

    **SP:** `sp_obtener_usuario`, `sp_codigo_crear`, `sp_registrar_auditoria`."""
    response.headers["Cache-Control"] = "no-store"
    return contenedor.auth.generar_codigo(actor, id_usuario)


# ----------------------------------------------------------------- Asignaciones

@router.get("/asignaciones", summary="Asignaciones de unidades a clientes",
            response_model=Pagina[AsignacionOut], responses=ADMIN_LECTURA)
def listar_asignaciones(contenedor: ContenedorDep, _actor: ActorAdmin,
                        id_vehiculo: Optional[int] = Query(None, gt=0),
                        id_usuario: Optional[int] = Query(None, gt=0),
                        vigentes: Optional[bool] = Query(None, description="Solo las vigentes"),
                        limite: int = Limite, desplazamiento: int = Desplazamiento):
    """**SP:** `sp_listar_asignaciones`."""
    return contenedor.asignaciones.listar(id_vehiculo, id_usuario, vigentes, limite, desplazamiento)


@router.post("/asignaciones", summary="Asignar una unidad a un cliente", status_code=201,
             response_model=AsignacionOut, responses=ADMIN_ESCRITURA)
def asignar_unidad(cuerpo: AsignacionCrear, contenedor: ContenedorDep, actor: ActorAdmin):
    """En una transacción: cierra la asignación vigente (si había), revoca el
    soporte otorgado, crea la nueva y marca la unidad como vendida.

    **SP:** `sp_asignar_unidad`, `sp_listar_asignaciones`, `sp_registrar_auditoria`."""
    return contenedor.asignaciones.asignar(actor, cuerpo.id_vehiculo, cuerpo.id_usuario)


@router.post("/asignaciones/{id_asignacion}/finalizar", summary="Finalizar una asignación",
             response_model=MensajeOut, responses=ADMIN_ESCRITURA)
def finalizar_asignacion(id_asignacion: IdAsignacion, cuerpo: AsignacionFinalizar,
                         contenedor: ContenedorDep, actor: ActorAdmin):
    """Deja la unidad en inventario, exhibición o baja y revoca el soporte.

    **SP:** `sp_finalizar_asignacion`, `sp_registrar_auditoria`."""
    contenedor.asignaciones.finalizar(actor, id_asignacion, cuerpo.motivo, cuerpo.estado_resultante)
    return {"mensaje": "Asignación finalizada.", "id": id_asignacion}


# ----------------------------------------------------------------- Auditoría

@router.get("/auditoria", summary="Bitácora de auditoría", response_model=Pagina[AuditoriaOut],
            responses=ADMIN_LECTURA)
def listar_auditoria(contenedor: ContenedorDep, _actor: ActorAdmin,
                     accion: Optional[str] = Query(None, max_length=60, description="Prefijo, p. ej. «unidad.»"),
                     id_usuario: Optional[int] = Query(None, gt=0),
                     recurso_tipo: Optional[str] = Query(None, max_length=30),
                     recurso_id: Optional[str] = Query(None, max_length=40),
                     desde: Optional[datetime] = Query(None, description="UTC, incluido"),
                     hasta: Optional[datetime] = Query(None, description="UTC, excluido"),
                     limite: int = Limite, desplazamiento: int = Desplazamiento):
    """De la más reciente a la más antigua. Solo inserción: no existe ruta
    para modificarla ni borrarla.

    **SP:** `sp_listar_auditoria`."""
    return contenedor.auditoria.listar(accion, id_usuario, recurso_tipo, recurso_id,
                                       desde, hasta, limite, desplazamiento)
