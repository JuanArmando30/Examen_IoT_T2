from app.core.exceptions import ConflictoNegocio, RecursoNoEncontrado


class ComandoService:
    """Catálogo de comandos: cada vehículo tiene el suyo."""

    def __init__(self, repositorio, vehiculos):
        self.repositorio = repositorio
        self.vehiculos = vehiculos

    def listar(self, id_vehiculo):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        return self.repositorio.obtener_comandos_vehiculo(id_vehiculo)

    def obtener_en_catalogo(self, id_vehiculo, id_comando=None, codigo=None):
        """Busca el comando SOLO dentro del catálogo de ese vehículo.

        Un comando de otro vehículo se rechaza con 404, aunque exista.
        """

        for comando in self.repositorio.obtener_comandos_vehiculo(
            id_vehiculo
        ):
            if id_comando is not None and comando["id_comando"] == id_comando:
                return comando

            if codigo is not None and comando["codigo"] == codigo:
                return comando

        referencia = (
            f"id {id_comando}" if id_comando is not None else f"código {codigo}"
        )
        raise RecursoNoEncontrado(
            f"El comando ({referencia}) no existe en el catálogo del "
            f"vehículo {id_vehiculo}."
        )

    def exigir_activo(self, comando):
        if not comando["activo"]:
            raise ConflictoNegocio(
                f"El comando {comando['nombre']} está inactivo."
            )

        return comando

    def buscar_detener(self, id_vehiculo):
        """Comando DETENER activo del vehículo (o None si no lo tiene)."""

        for comando in self.repositorio.obtener_comandos_vehiculo(
            id_vehiculo
        ):
            if comando["activo"] and comando["nombre"].upper() == "DETENER":
                return comando

        return None

    def _validar_duplicados(self, catalogo, nombre, codigo, excluir=None):
        for existente in catalogo:
            if existente["id_comando"] == excluir:
                continue

            if existente["codigo"] == codigo:
                raise ConflictoNegocio(
                    f"El código {codigo} ya está usado por el comando "
                    f"{existente['nombre']}."
                )

            if existente["nombre"].lower() == nombre.lower():
                raise ConflictoNegocio(
                    f"Ya existe un comando llamado {existente['nombre']}."
                )

    def crear(self, id_vehiculo, nombre, codigo, descripcion):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        catalogo = self.repositorio.obtener_comandos_vehiculo(id_vehiculo)
        self._validar_duplicados(catalogo, nombre, codigo)

        id_comando = self.repositorio.crear_comando(
            id_vehiculo, nombre, codigo, descripcion
        )
        return self.obtener_en_catalogo(id_vehiculo, id_comando=id_comando)

    def actualizar(
        self, id_vehiculo, id_comando, nombre, codigo, descripcion, activo,
    ):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        self.obtener_en_catalogo(id_vehiculo, id_comando=id_comando)

        catalogo = self.repositorio.obtener_comandos_vehiculo(id_vehiculo)
        self._validar_duplicados(catalogo, nombre, codigo, excluir=id_comando)

        self.repositorio.actualizar_comando(
            id_comando, nombre, codigo, descripcion, activo
        )
        return self.obtener_en_catalogo(id_vehiculo, id_comando=id_comando)

    def eliminar(self, id_vehiculo, id_comando):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        self.obtener_en_catalogo(id_vehiculo, id_comando=id_comando)
        # Si el comando está en una DEMO, MySQL lo impide (FK RESTRICT)
        # y el repositorio lo traduce a 409.
        self.repositorio.eliminar_comando(id_comando)
