"""Ensambla repositorio, servicios, gestor WebSocket y ejecutor de DEMO."""

from app.core.config import SeguridadSettings
from app.db.database import Database
from app.repositories.stored_procedure_repository import (
    StoredProcedureRepository,
)
from app.services.comando_service import ComandoService
from app.services.demo_ejecutor import DemoEjecutor
from app.services.demo_service import DemoService
from app.services.estado_service import EstadoService
from app.services.historial_service import HistorialService
from app.services.movimiento_service import MovimientoService
from app.services.vehiculo_service import VehiculoService
from app.websocket.gestor import GestorConexiones


class Contenedor:
    """Una sola instancia por aplicación (se crea al arrancar)."""

    def __init__(self, repositorio=None, seguridad=None, gestor=None):
        self.seguridad = seguridad or SeguridadSettings.from_env()
        self.repositorio = repositorio or StoredProcedureRepository(Database())
        self.gestor_ws = gestor or GestorConexiones()

        self.vehiculos = VehiculoService(self.repositorio)
        self.comandos = ComandoService(self.repositorio, self.vehiculos)
        self.estados = EstadoService(
            self.repositorio, self.vehiculos, self.comandos
        )
        self.historial = HistorialService(self.repositorio, self.vehiculos)
        self.movimientos = MovimientoService(
            self.repositorio, self.vehiculos, self.comandos
        )
        self.demos = DemoService(
            self.repositorio, self.vehiculos, self.comandos
        )
        self.demo_ejecutor = DemoEjecutor(
            self.demos, self.estados, self.comandos, self.gestor_ws
        )

    def verificar_base_datos(self):
        return self.repositorio.verificar()
