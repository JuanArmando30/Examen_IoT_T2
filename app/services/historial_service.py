LIMITE_HISTORIAL = 10


class HistorialService:
    """Consulta de la bitácora de movimientos INDIVIDUALES."""

    def __init__(self, repositorio, vehiculos):
        self.repositorio = repositorio
        self.vehiculos = vehiculos

    def ultimos(self, id_vehiculo):
        """Como máximo los 10 movimientos más recientes.

        - Vehículo inexistente -> 404 (RecursoNoEncontrado).
        - Vehículo sin movimientos -> lista vacía (consulta válida).
        El historial completo se conserva en RDS; solo se limita lo que
        devuelve el GET.
        """

        self.vehiculos.obtener_o_fallar(id_vehiculo)
        registros = self.repositorio.obtener_historial(id_vehiculo)
        return registros[:LIMITE_HISTORIAL]
