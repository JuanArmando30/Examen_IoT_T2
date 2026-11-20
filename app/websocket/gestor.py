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

    def __init__(self, websocket, sujeto=None):
        self.websocket = websocket
        self.sujeto = sujeto                 # quién es (Etapa 8): usuario, invitado, dispositivo, clave, abierto
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

    def registrar(self, id_vehiculo, websocket, sujeto=None):
        cliente = ClienteWS(websocket, sujeto)
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

    def clientes(self, id_vehiculo=None):
        """[(id_vehiculo, cliente)] de una unidad o de todas."""
        if id_vehiculo is not None:
            return [(id_vehiculo, c) for c in list(self._clientes.get(id_vehiculo, ()))]
        return [(v, c) for v, grupo in list(self._clientes.items()) for c in list(grupo)]

    def dispositivos(self, id_vehiculo):
        return sum(1 for c in self._clientes.get(id_vehiculo, ()) if c.sujeto and c.sujeto.tipo == "dispositivo")

    async def cerrar_cliente(self, id_vehiculo, cliente, codigo, motivo, mensaje=None):
        """Cierra UNA conexión (p. ej. permiso revocado) avisando antes el motivo."""
        self.desconectar(id_vehiculo, cliente)
        try:
            if mensaje is not None:
                await cliente.enviar(mensaje)
            await cliente.websocket.close(code=codigo, reason=motivo[:120])
        except Exception:
            pass

    async def cerrar_si(self, id_vehiculo, predicado, codigo, motivo, mensaje=None):
        """Cierra las conexiones de la unidad cuyo sujeto cumpla el predicado. Devuelve cuántas."""
        cerradas = 0
        for v, cliente in self.clientes(id_vehiculo):
            if cliente.sujeto is not None and predicado(cliente.sujeto):
                await self.cerrar_cliente(v, cliente, codigo, motivo, mensaje)
                cerradas += 1
        return cerradas

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
