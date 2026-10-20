from app.core.exceptions import ConflictoNegocio, RecursoNoEncontrado


class VehiculoService:
    """Reglas de negocio de los vehículos."""

    def __init__(self, repositorio):
        self.repositorio = repositorio

    def listar(self):
        return self.repositorio.obtener_vehiculos()

    def obtener_o_fallar(self, id_vehiculo):
        vehiculo = self.repositorio.obtener_vehiculo(id_vehiculo)

        if vehiculo is None:
            raise RecursoNoEncontrado(
                f"El vehículo {id_vehiculo} no existe."
            )

        return vehiculo

    def exigir_activo(self, id_vehiculo):
        vehiculo = self.obtener_o_fallar(id_vehiculo)

        if not vehiculo["activo"]:
            raise ConflictoNegocio(
                f"El vehículo {id_vehiculo} está inactivo."
            )

        return vehiculo

    def detalle(self, id_vehiculo):
        """Vehículo + catálogo de comandos + último estado + DEMO."""

        vehiculo = self.obtener_o_fallar(id_vehiculo)

        return {
            **vehiculo,
            "comandos": self.repositorio.obtener_comandos_vehiculo(
                id_vehiculo
            ),
            "estado": self.repositorio.obtener_estado(id_vehiculo),
            "demos": self.repositorio.obtener_demos(id_vehiculo),
        }

    def crear(self, nombre, modelo, descripcion, microcontrolador):
        id_vehiculo = self.repositorio.crear_vehiculo(
            nombre, modelo, descripcion, microcontrolador
        )
        return self.obtener_o_fallar(id_vehiculo)

    def actualizar(
        self, id_vehiculo, nombre, modelo, descripcion,
        microcontrolador, activo,
    ):
        self.obtener_o_fallar(id_vehiculo)
        self.repositorio.actualizar_vehiculo(
            id_vehiculo, nombre, modelo, descripcion,
            microcontrolador, activo,
        )
        return self.obtener_o_fallar(id_vehiculo)

    def eliminar(self, id_vehiculo):
        self.obtener_o_fallar(id_vehiculo)
        self.repositorio.eliminar_vehiculo(id_vehiculo)
