"""Administra los clientes WebSocket conectados a cada vehículo."""

import asyncio
import logging

logger = logging.getLogger(__name__)

TIMEOUT_ENVIO_SEGUNDOS = 5


class ClienteWS:
    """Envuelve un WebSocket con un candado de envío.

    Evita que dos corutinas escriban a la vez en la misma conexión
    (por ejemplo, un evento de DEMO y un 'pong').
    """

    def __init__(self, websocket):
        self.websocket = websocket
        self._candado = asyncio.Lock()

    async def enviar(self, mensaje):
        async with self._candado:
            await asyncio.wait_for(
                self.websocket.send_json(mensaje),
                timeout=TIMEOUT_ENVIO_SEGUNDOS,
            )


class GestorConexiones:
    """Clientes agrupados por id_vehiculo.

    Cada cliente solo recibe los eventos del vehículo que monitorea.
    Un cliente que falla se elimina sin afectar a los demás.
    """

    def __init__(self):
        self._clientes = {}

    def registrar(self, id_vehiculo, websocket):
        cliente = ClienteWS(websocket)
        self._clientes.setdefault(id_vehiculo, set()).add(cliente)
        return cliente

    def desconectar(self, id_vehiculo, cliente):
        grupo = self._clientes.get(id_vehiculo)

        if grupo is None:
            return

        grupo.discard(cliente)

        if not grupo:
            del self._clientes[id_vehiculo]

    def total_clientes(self, id_vehiculo):
        return len(self._clientes.get(id_vehiculo, ()))

    async def enviar(self, cliente, mensaje):
        await cliente.enviar(mensaje)

    async def _enviar_seguro(self, id_vehiculo, cliente, mensaje):
        try:
            await cliente.enviar(mensaje)
            return True
        except Exception as error:
            logger.warning(
                "Cliente WebSocket del vehículo %s descartado (%s).",
                id_vehiculo, error.__class__.__name__,
            )
            self.desconectar(id_vehiculo, cliente)

            try:
                await cliente.websocket.close()
            except Exception:
                pass

            return False

    async def difundir(self, id_vehiculo, mensaje):
        """Envía el mensaje a todos los clientes de ese vehículo.

        Devuelve cuántos lo recibieron. Nunca lanza excepciones por fallos
        de un cliente.
        """

        clientes = list(self._clientes.get(id_vehiculo, ()))

        if not clientes:
            return 0

        resultados = await asyncio.gather(
            *(self._enviar_seguro(id_vehiculo, c, mensaje) for c in clientes)
        )
        return sum(1 for ok in resultados if ok)
