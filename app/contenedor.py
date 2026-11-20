"""Ensambla repositorio, servicios, gestor WebSocket y ejecutor de DEMO."""

from app.core.config import AuthSettings, SeguridadSettings
from app.db.database import Database
from app.repositories.stored_procedure_repository import (
    StoredProcedureRepository,
)
from app.services.administracion import (
    AsignacionService,
    AuditoriaService,
    EsquemaBD,
    MetricasService,
    ModeloService,
    UnidadService,
    UsuarioService,
)
from app.services.auth_service import AuthService
from app.services.comando_service import ComandoService
from app.services.demo_ejecutor import DemoEjecutor
from app.services.demo_service import DemoService
from app.services.estado_service import EstadoService
from app.services.historial_service import HistorialService
from app.services.invitado_service import InvitadoService
from app.services.movimiento_service import MovimientoService
from app.services.vehiculo_service import VehiculoService
from app.websocket.gestor import GestorConexiones


class Contenedor:
    """Una sola instancia por aplicación (se crea al arrancar)."""

    def __init__(self, repositorio=None, seguridad=None, gestor=None, auth=None):
        self.seguridad = seguridad or SeguridadSettings.from_env()
        self.config_auth = auth or AuthSettings.from_env()
        self.repositorio = repositorio or StoredProcedureRepository(Database())
        self.gestor_ws = gestor or GestorConexiones()
        # Versión de la base: activa las funciones de Administración cuando existe V009.
        self.esquema = EsquemaBD(self.repositorio)

        self.vehiculos = VehiculoService(self.repositorio, self.esquema)
        self.comandos = ComandoService(self.repositorio, self.vehiculos)
        self.estados = EstadoService(
            self.repositorio, self.vehiculos, self.comandos
        )
        self.historial = HistorialService(
            self.repositorio, self.vehiculos, self.esquema
        )
        self.movimientos = MovimientoService(
            self.repositorio, self.vehiculos, self.comandos, self.esquema
        )
        # Bitácora (Etapa 3): la usan Administración y las DEMO privadas.
        self.auditoria = AuditoriaService(self.repositorio, self.esquema)
        self.demos = DemoService(
            self.repositorio, self.vehiculos, self.comandos, self.esquema, self.auditoria
        )
        self.demo_ejecutor = DemoEjecutor(
            self.demos, self.estados, self.comandos, self.gestor_ws
        )
        self.demos.ejecutor = self.demo_ejecutor

        # ---- Administración (Etapa 3) ----
        self.modelos = ModeloService(self.repositorio, self.esquema, self.auditoria)
        self.unidades = UnidadService(
            self.repositorio, self.esquema, self.auditoria, self.modelos,
            self.demo_ejecutor,
        )
        self.usuarios = UsuarioService(self.repositorio, self.esquema, self.auditoria)
        self.asignaciones = AsignacionService(
            self.repositorio, self.esquema, self.auditoria, self.unidades,
            self.usuarios, self.demo_ejecutor,
        )
        self.metricas = MetricasService(self.repositorio, self.esquema)

        # ---- Sesiones y autorización por unidad (Etapa 4) ----
        self.auth = AuthService(
            self.repositorio, self.esquema, self.auditoria, self.usuarios, self.config_auth,
        )

        # ---- Invitados y reserva de exhibición (Etapa 7) ----
        self.invitados = InvitadoService(
            self.repositorio, self.esquema, self.auditoria, self.config_auth, self.comandos,
            self.movimientos, self.demos, self.demo_ejecutor, self.gestor_ws,
        )

    def verificar_base_datos(self):
        return self.repositorio.verificar()
