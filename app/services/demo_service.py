from app.core.exceptions import ConflictoNegocio, RecursoNoEncontrado


class DemoService:
    """DEMO y sus N movimientos configurables."""

    def __init__(self, repositorio, vehiculos, comandos):
        self.repositorio = repositorio
        self.vehiculos = vehiculos
        self.comandos = comandos

    # ------------------------- DEMO -------------------------

    def listar(self, id_vehiculo):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        return self.repositorio.obtener_demos(id_vehiculo)

    def obtener_de_vehiculo(self, id_vehiculo, id_demo):
        """La DEMO debe existir Y pertenecer a ese vehículo."""

        for demo in self.repositorio.obtener_demos(id_vehiculo):
            if demo["id_demo"] == id_demo:
                return demo

        raise RecursoNoEncontrado(
            f"La DEMO {id_demo} no existe en el vehículo {id_vehiculo}."
        )

    def crear(self, id_vehiculo, nombre, descripcion):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        id_demo = self.repositorio.crear_demo(
            id_vehiculo, nombre, descripcion
        )
        return self.obtener_de_vehiculo(id_vehiculo, id_demo)

    def actualizar(self, id_vehiculo, id_demo, nombre, descripcion, activo):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        self.obtener_de_vehiculo(id_vehiculo, id_demo)
        self.repositorio.actualizar_demo(
            id_demo, nombre, descripcion, activo
        )
        return self.obtener_de_vehiculo(id_vehiculo, id_demo)

    def eliminar(self, id_vehiculo, id_demo):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        self.obtener_de_vehiculo(id_vehiculo, id_demo)
        self.repositorio.eliminar_demo(id_demo)

    # ------------------- MOVIMIENTOS DE DEMO -------------------

    def movimientos(self, id_vehiculo, id_demo):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        self.obtener_de_vehiculo(id_vehiculo, id_demo)
        return self.repositorio.obtener_movimientos_demo(id_demo)

    def _obtener_movimiento(self, id_demo, id_movimiento):
        for movimiento in self.repositorio.obtener_movimientos_demo(id_demo):
            if movimiento["id_demo_movimiento"] == id_movimiento:
                return movimiento

        raise RecursoNoEncontrado(
            f"El movimiento {id_movimiento} no pertenece a la DEMO {id_demo}."
        )

    def _validar_orden_libre(self, id_demo, orden, excluir=None):
        for movimiento in self.repositorio.obtener_movimientos_demo(id_demo):
            if movimiento["id_demo_movimiento"] == excluir:
                continue

            if movimiento["orden"] == orden:
                raise ConflictoNegocio(
                    f"La DEMO {id_demo} ya tiene un movimiento con "
                    f"orden {orden}."
                )

    def agregar_movimiento(
        self, id_vehiculo, id_demo, id_comando, orden, duracion_ms, pausa_ms,
    ):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        self.obtener_de_vehiculo(id_vehiculo, id_demo)

        # El comando debe ser del catálogo de ESTE vehículo y estar activo.
        comando = self.comandos.obtener_en_catalogo(
            id_vehiculo, id_comando=id_comando
        )
        self.comandos.exigir_activo(comando)
        self._validar_orden_libre(id_demo, orden)

        self.repositorio.agregar_movimiento_demo(
            id_demo, id_comando, orden, duracion_ms, pausa_ms
        )

        # sp_agregar_movimiento_demo no devuelve el ID: se localiza por orden.
        for movimiento in self.repositorio.obtener_movimientos_demo(id_demo):
            if movimiento["orden"] == orden:
                return movimiento

        raise RecursoNoEncontrado("No se pudo recuperar el movimiento creado.")

    def actualizar_movimiento(
        self, id_vehiculo, id_demo, id_movimiento,
        id_comando, orden, duracion_ms, pausa_ms,
    ):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        self.obtener_de_vehiculo(id_vehiculo, id_demo)
        self._obtener_movimiento(id_demo, id_movimiento)

        comando = self.comandos.obtener_en_catalogo(
            id_vehiculo, id_comando=id_comando
        )
        self.comandos.exigir_activo(comando)
        self._validar_orden_libre(id_demo, orden, excluir=id_movimiento)

        self.repositorio.actualizar_movimiento_demo(
            id_movimiento, id_comando, orden, duracion_ms, pausa_ms
        )
        return self._obtener_movimiento(id_demo, id_movimiento)

    def eliminar_movimiento(self, id_vehiculo, id_demo, id_movimiento):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        self.obtener_de_vehiculo(id_vehiculo, id_demo)
        self._obtener_movimiento(id_demo, id_movimiento)
        self.repositorio.eliminar_movimiento_demo(id_movimiento)

    # --------------------- EJECUCIÓN ---------------------

    def preparar_ejecucion(self, id_vehiculo, id_demo):
        """Valida todo ANTES de arrancar y devuelve (demo, movimientos).

        Los N movimientos se leen de RDS con sp_obtener_movimientos_demo:
        no existe ninguna secuencia fija en el código.
        """

        self.vehiculos.exigir_activo(id_vehiculo)
        demo = self.obtener_de_vehiculo(id_vehiculo, id_demo)

        if not demo["activo"]:
            raise ConflictoNegocio(f"La DEMO {id_demo} está inactiva.")

        movimientos = self.repositorio.obtener_movimientos_demo(id_demo)

        if not movimientos:
            raise ConflictoNegocio(
                f"La DEMO {id_demo} no tiene movimientos configurados."
            )

        catalogo = {
            c["id_comando"]: c
            for c in self.repositorio.obtener_comandos_vehiculo(id_vehiculo)
        }
        inactivos = sorted({
            m["comando"]
            for m in movimientos
            if m["id_comando"] not in catalogo
            or not catalogo[m["id_comando"]]["activo"]
        })

        if inactivos:
            raise ConflictoNegocio(
                "La DEMO usa comandos inactivos o ajenos al vehículo: "
                + ", ".join(inactivos)
            )

        return demo, movimientos
