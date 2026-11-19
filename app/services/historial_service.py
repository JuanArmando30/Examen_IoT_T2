LIMITE_HISTORIAL = 10


class HistorialService:
    """Consulta de la bitácora de movimientos INDIVIDUALES."""

    def __init__(self, repositorio, vehiculos, esquema=None):
        self.repositorio = repositorio
        self.vehiculos = vehiculos
        self.esquema = esquema

    def ultimos(self, id_vehiculo):
        """Como máximo los 10 movimientos más recientes.

        - Vehículo inexistente -> 404 (RecursoNoEncontrado).
        - Vehículo sin movimientos -> lista vacía (consulta válida).
        - Con V009 se usa sp_obtener_historial_reciente (LIMIT en la base,
          índice de V006); sin ella, el SP original y se recorta aquí.
        El historial completo se conserva en RDS; solo se limita lo que
        devuelve el GET.
        """

        self.vehiculos.obtener_o_fallar(id_vehiculo)
        if self.esquema is not None and self.esquema.tiene_administracion():
            return self.repositorio.obtener_historial_reciente(id_vehiculo, LIMITE_HISTORIAL)
        registros = self.repositorio.obtener_historial(id_vehiculo)
        return registros[:LIMITE_HISTORIAL]
