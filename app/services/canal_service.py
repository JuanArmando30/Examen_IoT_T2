"""Canal en tiempo real (WebSocket) por UNIDAD, con autenticación y autorización (Etapa 8).

Quién puede suscribirse a /ws/vehiculos/{id}:
- Navegador con TICKET de un solo uso (30 s) pedido en POST /ws/ticket con su
  credencial: token (dueño; admin según estado/soporte — mismas reglas que REST),
  reserva de invitado (solo su unidad) o clave X-API-Key (transición).
  El ticket viaja en la URL, pero caduca en 30 s y se borra al usarse.
- El ESP32 con su CREDENCIAL de dispositivo (cabecera X-Dispositivo). Su conexión
  es la evidencia real de que la unidad está en línea (`conectado`) y es el
  único que puede enviar REPORTES de ejecución.
- Transición: con WS_ABIERTO=true (por defecto) también se aceptan conexiones
  sin nada, como antes (firmware y páginas anteriores).

Revocación: cada 10 s se revalida a cada suscriptor (dueño que dejó de serlo,
usuario desactivado, soporte vencido o revocado, credencial revocada) y se
cierra su conexión con 4403. El fin de una reserva de invitado cierra la suya
al instante.
"""

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from app.core import tokens
from app.core.exceptions import (
    ErrorAplicacion, NoAutorizado, NoConfigurado, Prohibido, RecursoNoEncontrado,
)
from app.core.limite import LimitadorTasa
from app.core.security import identificar_rol
from app.services.auth_service import Principal
from app.websocket import eventos

logger = logging.getLogger(__name__)

TICKET_S = 30
REVALIDAR_S = 10
MAX_TICKETS = 2000
CIERRE_REVOCADO = 4403
ACCIONES_REPORTE = {"ejecutando", "detenido", "ignorado"}


@dataclass(frozen=True)
class Sujeto:
    """Quién está detrás de una conexión WebSocket."""

    tipo: str                         # usuario | invitado | clave | abierto | dispositivo
    id_usuario: Optional[int] = None
    rol: Optional[str] = None
    id_sesion: Optional[int] = None
    id_credencial: Optional[int] = None

    def publico(self):
        return {"tipo": self.tipo, "rol": self.rol}


class CanalService:
    def __init__(self, repositorio, esquema, auditoria, config_auth, seguridad, auth, invitados, estados, gestor):
        self.repositorio = repositorio
        self.esquema = esquema
        self.auditoria = auditoria
        self.config_auth = config_auth
        self.seguridad = seguridad
        self.auth = auth
        self.invitados = invitados
        self.estados = estados
        self.gestor = gestor
        self._tickets = {}                # ticket -> (id_vehiculo, sujeto, caduca monotonic)
        self._tarea = None
        self.limite_tickets = LimitadorTasa(60, 60)
        self.limite_reportes = LimitadorTasa(30, 1)

    # ------------------------------------------------------------ tickets (navegador)

    def emitir_ticket(self, id_vehiculo, ip, principal=None, token_invitado=None, clave=None):
        self.limite_tickets.registrar(ip)
        if token_invitado:
            actor = self.invitados.actor(token_invitado, id_vehiculo)
            sujeto = Sujeto("invitado", rol="invitado", id_sesion=actor.id_sesion)
        elif principal is not None:
            self.auth.exigir_acceso_unidad(principal, id_vehiculo)
            sujeto = Sujeto("usuario", id_usuario=principal.id_usuario, rol=principal.rol)
        elif clave:
            rol = identificar_rol(clave, self.seguridad)
            if rol is None:
                raise NoAutorizado("La clave X-API-Key no es válida.")
            sujeto = Sujeto("clave", rol=rol)
        elif self.config_auth.ws_abierto:
            sujeto = Sujeto("abierto")
        else:
            raise NoAutorizado("Inicia sesión (o usa tu reserva de invitado) para recibir eventos de esta unidad.")
        self._limpiar_tickets()
        ticket = secrets.token_urlsafe(24)
        self._tickets[ticket] = (id_vehiculo, sujeto, time.monotonic() + TICKET_S)
        return {"ticket": ticket, "expira_en_s": TICKET_S, "sujeto": sujeto.publico()}

    def _limpiar_tickets(self):
        ahora = time.monotonic()
        for t in [t for t, (_, _, caduca) in self._tickets.items() if caduca <= ahora]:
            self._tickets.pop(t, None)
        while len(self._tickets) >= MAX_TICKETS:
            self._tickets.pop(next(iter(self._tickets)))

    # ------------------------------------------------------------ autorizar la conexión

    def autorizar(self, id_vehiculo, ticket=None, secreto_dispositivo=None):
        """Sujeto de la conexión o error (401 sin credencial válida, 403 sin permiso)."""
        if secreto_dispositivo:
            return self._autorizar_dispositivo(id_vehiculo, secreto_dispositivo)
        if ticket:
            dato = self._tickets.pop(ticket, None)                      # un solo uso
            if dato is None or dato[2] <= time.monotonic():
                raise NoAutorizado("El ticket del WebSocket no es válido o caducó: pide otro.")
            if dato[0] != id_vehiculo:
                raise Prohibido("Ese ticket es de otra unidad.")
            return dato[1]
        if self.config_auth.ws_abierto:
            return Sujeto("abierto")
        raise NoAutorizado("Falta el ticket del WebSocket (POST /ws/ticket).")

    def _autorizar_dispositivo(self, id_vehiculo, secreto):
        if not self.config_auth.configurado:
            raise NoConfigurado("La credencial del dispositivo necesita TOKEN_SECRETO en el servidor.")
        self.esquema.exigir_dispositivo()
        cred = self.repositorio.dispositivo_validar(tokens.huella(self.config_auth, secreto))
        if cred is None:
            raise NoAutorizado("Credencial de dispositivo no válida o revocada.")
        if cred["id_vehiculo"] != id_vehiculo:
            raise Prohibido("Esa credencial es de otra unidad.")
        return Sujeto("dispositivo", rol="dispositivo", id_credencial=int(cred["id_credencial"]))

    def sigue_autorizado(self, id_vehiculo, sujeto):
        """¿Conserva el permiso? (se consulta cada pocos segundos)."""
        try:
            if sujeto.tipo == "usuario":
                u = self.repositorio.obtener_usuario_auth(sujeto.id_usuario)
                if u is None or not u["activo"]:
                    return False
                principal = Principal(id_usuario=u["id_usuario"], rol=u["rol"], nombre=u["nombre"], correo=u["correo"])
                self.auth.exigir_acceso_unidad(principal, id_vehiculo)
                return True
            if sujeto.tipo == "invitado":
                r = self.invitados.reserva_de(id_vehiculo)
                return r is not None and r.id_sesion == sujeto.id_sesion
            if sujeto.tipo == "dispositivo":
                e = self.repositorio.dispositivo_estado(id_vehiculo)
                return bool(e and e["vigente"] and e["id_credencial"] == sujeto.id_credencial)
            if sujeto.tipo == "abierto":
                return self.config_auth.ws_abierto
            return True                                                   # clave (transición)
        except (Prohibido, RecursoNoEncontrado, NoAutorizado):
            return False
        except ErrorAplicacion:
            return True               # RDS caída: no se expulsa a nadie por un fallo transitorio

    async def revalidar(self):
        cerradas = 0
        for id_vehiculo, cliente in self.gestor.clientes():
            if cliente.sujeto is None:
                continue
            if not await asyncio.to_thread(self.sigue_autorizado, id_vehiculo, cliente.sujeto):
                await self.gestor.cerrar_cliente(
                    id_vehiculo, cliente, CIERRE_REVOCADO, "Permiso revocado",
                    eventos.error(id_vehiculo, "WS_REVOCADO", "Ya no tienes permiso para recibir los eventos de esta unidad."))
                if cliente.sujeto.tipo == "dispositivo":
                    await self.dispositivo_desconectado(id_vehiculo)
                cerradas += 1
        return cerradas

    async def _vigilar(self):
        while True:
            await asyncio.sleep(REVALIDAR_S)
            try:
                await self.revalidar()
            except Exception:
                logger.exception("Error al revalidar las suscripciones WebSocket")

    async def iniciar(self):
        self._tarea = asyncio.create_task(self._vigilar())

    async def cerrar(self):
        if self._tarea is not None:
            self._tarea.cancel()

    # ------------------------------------------------------------ dispositivo

    async def _publicar_conexion(self, id_vehiculo, conectado):
        try:
            estado = await asyncio.to_thread(self.estados.actualizar, id_vehiculo, conectado)
            await self.gestor.difundir(id_vehiculo, eventos.estado_actualizado(id_vehiculo, estado))
        except Exception:
            logger.exception("No se pudo registrar la conexión del dispositivo de la unidad %s", id_vehiculo)

    async def dispositivo_conectado(self, id_vehiculo):
        await self._publicar_conexion(id_vehiculo, True)

    async def dispositivo_desconectado(self, id_vehiculo):
        if self.gestor.dispositivos(id_vehiculo) == 0:
            await self._publicar_conexion(id_vehiculo, False)

    async def mensaje_dispositivo(self, id_vehiculo, texto):
        """Reporte de ejecución del ESP32: {"evento":"reporte","codigo":N,"accion":"ejecutando|detenido|ignorado"}."""
        try:
            self.limite_reportes.registrar(id_vehiculo)
            dato = json.loads(texto)
        except (ErrorAplicacion, ValueError):
            return False
        if not isinstance(dato, dict) or dato.get("evento") != "reporte" or dato.get("accion") not in ACCIONES_REPORTE:
            return False
        codigo = dato.get("codigo")
        duracion = dato.get("duracion_ms")
        motivo = dato.get("motivo")
        if codigo is not None and (not isinstance(codigo, int) or not -1 <= codigo <= 65535):
            return False
        if duracion is not None and (not isinstance(duracion, int) or not 0 <= duracion <= 600000):
            return False
        motivo = motivo[:60] if isinstance(motivo, str) else None
        await self.gestor.difundir(id_vehiculo, eventos.reporte_dispositivo(id_vehiculo, codigo, dato["accion"], duracion, motivo))
        return True

    def estado_dispositivo(self, id_vehiculo):
        self.esquema.exigir_dispositivo()
        e = self.repositorio.dispositivo_estado(id_vehiculo)
        return {
            "id_vehiculo": id_vehiculo,
            "conectado": self.gestor.dispositivos(id_vehiculo) > 0,
            "credencial": None if e is None else {
                "id_credencial": e["id_credencial"], "creada_en": e["creada_en"],
                "ultimo_uso": e["ultimo_uso"], "vigente": bool(e["vigente"]),
            },
            "ws_abierto": self.config_auth.ws_abierto,
        }

    def credencial_crear(self, actor, id_vehiculo):
        """Nueva credencial (revoca la anterior). El secreto se muestra UNA vez."""
        if not self.config_auth.configurado:
            raise NoConfigurado("La credencial del dispositivo necesita TOKEN_SECRETO en el servidor.")
        self.esquema.exigir_dispositivo()
        secreto = "dev_" + secrets.token_urlsafe(32)
        id_credencial = self.repositorio.dispositivo_crear(id_vehiculo, tokens.huella(self.config_auth, secreto))
        self.auditoria.registrar(actor, "dispositivo.credencial", "unidad", id_vehiculo, {"id_credencial": id_credencial})
        return {"id_vehiculo": id_vehiculo, "id_credencial": id_credencial, "secreto": secreto}

    async def credencial_revocar(self, actor, id_vehiculo):
        self.esquema.exigir_dispositivo()
        revocadas = await asyncio.to_thread(self.repositorio.dispositivo_revocar, id_vehiculo)
        cerradas = await self.gestor.cerrar_si(
            id_vehiculo, lambda s: s.tipo == "dispositivo", CIERRE_REVOCADO, "Credencial revocada",
            eventos.error(id_vehiculo, "WS_REVOCADO", "La credencial del dispositivo fue revocada."))
        if cerradas:
            await self.dispositivo_desconectado(id_vehiculo)
        await asyncio.to_thread(self.auditoria.registrar, actor, "dispositivo.revocar", "unidad", id_vehiculo,
                                {"revocadas": revocadas})
        return {**await asyncio.to_thread(self.estado_dispositivo, id_vehiculo), "revocadas": revocadas}
