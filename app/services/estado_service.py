from app.core.exceptions import RecursoNoEncontrado


class EstadoService:
    """Último estado registrado del vehículo (tabla estado_vehiculo)."""

    def __init__(self, repositorio, vehiculos, comandos):
        self.repositorio = repositorio
        self.vehiculos = vehiculos
        self.comandos = comandos

    def obtener_o_none(self, id_vehiculo):
        return self.repositorio.obtener_estado(id_vehiculo)

    def obtener(self, id_vehiculo):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        estado = self.repositorio.obtener_estado(id_vehiculo)

        if estado is None:
            raise RecursoNoEncontrado(
                f"El vehículo {id_vehiculo} todavía no tiene un estado "
                "registrado."
            )

        return estado

    def actualizar(self, id_vehiculo, conectado, id_comando=None):
        """Cambia el indicador de conexión (y opcionalmente el comando).

        Si no se envía id_comando se conserva el último comando.
        """

        self.vehiculos.obtener_o_fallar(id_vehiculo)

        if id_comando is not None:
            self.comandos.obtener_en_catalogo(
                id_vehiculo, id_comando=id_comando
            )
        else:
            actual = self.repositorio.obtener_estado(id_vehiculo)
            id_comando = actual["id_comando"] if actual else None

        self.repositorio.actualizar_estado(
            id_vehiculo, id_comando, conectado
        )
        return self.repositorio.obtener_estado(id_vehiculo)

    def fijar_comando(self, id_vehiculo, id_comando):
        """Actualiza solo el último comando, conservando 'conectado'.

        La usa la DEMO. NO escribe en el historial.
        """

        with self.repositorio.transaccion() as tx:
            actual = tx.obtener_estado(id_vehiculo)
            conectado = bool(actual["conectado"]) if actual else False
            tx.actualizar_estado(id_vehiculo, id_comando, conectado)
