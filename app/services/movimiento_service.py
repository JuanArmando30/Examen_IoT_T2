from app.core.exceptions import SolicitudInvalida


class MovimientoService:
    """Flujo de MOVIMIENTO INDIVIDUAL.

    validar -> (sp_actualizar_estado + sp_registrar_historial en UNA
    transacción) -> devolver el resultado. La notificación WebSocket la
    hace la capa API DESPUÉS de que esta transacción se confirmó.
    """

    def __init__(self, repositorio, vehiculos, comandos):
        self.repositorio = repositorio
        self.vehiculos = vehiculos
        self.comandos = comandos

    def registrar(self, id_vehiculo, id_comando=None, codigo=None,
                  origen="API"):
        if id_comando is None and codigo is None:
            raise SolicitudInvalida("Indica id_comando o codigo.")

        # 1) Validaciones: si algo falla, NO se toca estado ni historial.
        self.vehiculos.exigir_activo(id_vehiculo)
        comando = self.comandos.obtener_en_catalogo(
            id_vehiculo, id_comando=id_comando, codigo=codigo
        )
        self.comandos.exigir_activo(comando)
        origen = origen.strip().upper()

        # 2) Transacción atómica: ambos SP o ninguno.
        with self.repositorio.transaccion() as tx:
            actual = tx.obtener_estado(id_vehiculo)

            # Recibir un POST no demuestra que el microcontrolador esté
            # conectado: se CONSERVA el valor que ya tenía (FALSE si es el
            # primer registro).
            conectado = bool(actual["conectado"]) if actual else False

            tx.actualizar_estado(id_vehiculo, comando["id_comando"], conectado)
            tx.registrar_historial(id_vehiculo, comando["id_comando"], origen)
        # <- COMMIT hecho. Recién ahora es seguro avisar por WebSocket.

        estado = self.repositorio.obtener_estado(id_vehiculo)

        return {
            "id_vehiculo": id_vehiculo,
            "id_comando": comando["id_comando"],
            "comando": comando["nombre"],
            "codigo": comando["codigo"],
            "origen": origen,
            "conectado": bool(estado["conectado"]) if estado else conectado,
            "fecha_actualizacion": (
                estado["fecha_actualizacion"] if estado else None
            ),
            "mensaje": (
                "Movimiento registrado en estado_vehiculo e "
                "historial_comandos."
            ),
        }
