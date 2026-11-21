"""INVITADOS: catálogo público y reserva temporal de la unidad de EXHIBICIÓN (Etapa 7).

Reglas:
- Interruptor de exhibición (lo abre la empresa cuando hay alguien supervisando).
  Vive en memoria y caduca solo: si la API se reinicia queda CERRADO (estado seguro).
- Reserva EXCLUSIVA de 5 min, una a la vez, sin fila. Límites por red (hash de la
  IP con TOKEN_SECRETO) contados en RDS: 3 por hora y 10 min entre reservas.
- Mientras dura, nadie más controla esa unidad (ni clave, ni control abierto, ni
  otra sesión), salvo DETENER/cancelar, que siempre tienen prioridad.
- El invitado solo usa comandos que el modelo permite a invitados (DETENER
  siempre) y DEMO de fábrica cuyos pasos sean todos permitidos.
- Vigilante (cada segundo): al CADUCAR o si el invitado deja de dar señales
  (latido) la API cancela la DEMO, envía DETENER y libera la unidad.
- Nunca sobre unidades de compradores: el SP solo reserva unidades en 'exhibicion'.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.core import tokens
from app.core.exceptions import (
    ConflictoNegocio, DemasiadosIntentos, NoAutorizado, NoConfigurado, Prohibido, RecursoNoEncontrado,
    SolicitudInvalida,
)
from app.core.limite import LimitadorTasa
from app.services.administracion import Actor
from app.websocket import eventos

logger = logging.getLogger(__name__)

MINUTOS_RESERVA = 1                 # prueba corta: 1 minuto
MAX_RESERVAS_POR_HORA = 5
ENFRIAMIENTO_MIN = 3                # espera tras usarla o terminarla (no tras una desconexión, V014)
LATIDO_MAX_S = 15            # sin latido durante este tiempo → «desconexión»
VIGILANCIA_S = 1
MAX_HORAS_EXHIBICION = 8
ORIGEN_SISTEMA = "SISTEMA_INVITADO"


def _ahora():
    return datetime.now(timezone.utc)


def _mmss(segundos):
    segundos = max(int(segundos), 0)
    return f"{segundos // 60}:{segundos % 60:02d}"


@dataclass
class Reserva:
    id_reserva: int
    id_sesion: int
    id_vehiculo: int
    huella: str
    expira: datetime
    comandos: dict                                   # id_comando -> {nombre, codigo, tipo}
    ultimo_latido: float = field(default_factory=time.monotonic)

    def segundos(self):
        return max(int((self.expira - _ahora()).total_seconds()), 0)


class InvitadoService:
    def __init__(self, repositorio, esquema, auditoria, auth, comandos, movimientos, demos, demo_ejecutor, gestor):
        self.repositorio = repositorio
        self.esquema = esquema
        self.auditoria = auditoria
        self.auth = auth
        self.comandos = comandos
        self.movimientos = movimientos
        self.demos = demos
        self.demo_ejecutor = demo_ejecutor
        self.gestor = gestor
        self._exhibicion = {}            # id_vehiculo -> (hasta UTC, quién la abrió)
        self._activas = {}               # id_vehiculo -> Reserva
        self._tarea = None
        self._candado = asyncio.Lock()
        self.limite_reservar = LimitadorTasa(10, 600)

    # ------------------------------------------------------------ utilidades

    def _exigir(self):
        if not self.auth.configurado:
            raise NoConfigurado("Las reservas de invitado necesitan TOKEN_SECRETO en el servidor.")
        self.esquema.exigir_invitados()

    def _sistema(self):
        return Actor(id_usuario=None, rol="sistema", via="invitado")

    def exhibicion_abierta(self, id_vehiculo):
        abierta = self._exhibicion.get(id_vehiculo)
        return bool(abierta and abierta[0] > _ahora())

    def reserva_de(self, id_vehiculo):
        r = self._activas.get(id_vehiculo)
        return r if r is not None and r.segundos() > 0 else None

    def _por_token(self, token):
        if not token or not self.auth.configurado:
            return None
        huella = tokens.huella(self.auth, token)
        return next((r for r in self._activas.values() if r.huella == huella and r.segundos() > 0), None)

    # ------------------------------------------------------------ catálogo y reserva

    def catalogo(self):
        self.esquema.exigir_invitados()
        filas = self.repositorio.catalogo_exhibicion()
        salida = []
        for f in filas:
            r = self.reserva_de(f["id_vehiculo"])
            abierta = self.exhibicion_abierta(f["id_vehiculo"])
            salida.append({
                "id_vehiculo": f["id_vehiculo"], "nombre": f["nombre"], "descripcion": f.get("descripcion"),
                "es_simulada": bool(f.get("es_simulada")), "modelo": f.get("modelo"),
                "modelo_descripcion": f.get("modelo_descripcion"), "microcontrolador": f.get("microcontrolador"),
                "conectado": None if f.get("conectado") is None else bool(f["conectado"]),
                "exhibicion_abierta": abierta,
                "disponible": abierta and r is None,
                "segundos_reserva": r.segundos() if r else 0,
                "minutos_reserva": MINUTOS_RESERVA,
            })
        return salida

    async def reservar(self, id_vehiculo, ip):
        self._exigir()
        self.limite_reservar.registrar(ip)
        if not self.exhibicion_abierta(id_vehiculo):
            raise ConflictoNegocio("La exhibición está cerrada en este momento: la empresa la abre cuando hay "
                                   "alguien supervisando la unidad.")
        token = tokens.secreto_aleatorio()
        huella = tokens.huella(self.auth, token)
        red = tokens.huella(self.auth, f"red:{ip}")
        async with self._candado:
            r = await asyncio.to_thread(self.repositorio.invitado_reservar, id_vehiculo, huella, red,
                                        MINUTOS_RESERVA, MAX_RESERVAS_POR_HORA, ENFRIAMIENTO_MIN)
            resultado = r.get("resultado")
            if resultado == "propia":
                raise ConflictoNegocio(
                    "Ya tienes una reserva activa (en otra pestaña o ventana). Vuelve a ella; "
                    f"si la cerraste, se libera sola en unos segundos (termina en {_mmss(r.get('segundos') or 0)}).")
            if resultado == "ocupada":
                raise ConflictoNegocio(f"La unidad está reservada por otro visitante. Se libera en {_mmss(r.get('segundos') or 0)}.")
            if resultado in ("limite", "enfriamiento"):
                raise DemasiadosIntentos(
                    f"Ya usaste la unidad hace poco. Podrás reservarla de nuevo en {_mmss(r.get('segundos') or 0)}.")
            if resultado != "ok":
                raise ConflictoNegocio("Esta unidad no está disponible para invitados.")
            comandos = await asyncio.to_thread(self.repositorio.comandos_invitado, id_vehiculo)
            reserva = Reserva(
                id_reserva=int(r["id_reserva"]), id_sesion=int(r["id_sesion"]), id_vehiculo=id_vehiculo,
                huella=huella, expira=_ahora() + timedelta(seconds=int(r["segundos"])),
                comandos={c["id_comando"]: c for c in comandos},
            )
            self._activas[id_vehiculo] = reserva
        await asyncio.to_thread(self.auditoria.registrar, Actor(None, "invitado", "invitado", reserva.id_sesion),
                                "invitado.reservar", "unidad", id_vehiculo,
                                {"id_reserva": reserva.id_reserva, "minutos": MINUTOS_RESERVA})
        return {"token_invitado": token, **(await asyncio.to_thread(self.estado_reserva, reserva))}

    def estado_reserva(self, reserva):
        return {
            "id_reserva": reserva.id_reserva, "id_vehiculo": reserva.id_vehiculo,
            "expira_en": reserva.expira, "segundos_restantes": reserva.segundos(),
            "latido_max_s": LATIDO_MAX_S,
            "comandos": sorted(({"id_comando": i, "nombre": c["nombre"], "codigo": c["codigo"], "tipo": c.get("tipo")}
                                for i, c in reserva.comandos.items()), key=lambda c: c["codigo"]),
            "demos": self.demos_permitidas(reserva),
        }

    def estado(self, token):
        r = self._exigir_token(token)
        return self.estado_reserva(r)

    def _exigir_token(self, token):
        r = self._por_token(token)
        if r is None:
            raise NoAutorizado("Tu reserva terminó o no es válida. Puedes volver al catálogo.")
        return r

    def latido(self, token):
        r = self._exigir_token(token)
        r.ultimo_latido = time.monotonic()
        return {"segundos_restantes": r.segundos(), "en_demo": self.demo_ejecutor.esta_ejecutando(r.id_vehiculo)}

    async def terminar(self, token):
        r = self._exigir_token(token)
        await self.finalizar(r.id_vehiculo, "cancelada")

    # ------------------------------------------------------------ autorización

    def actor(self, token, id_vehiculo):
        """Actor del invitado para CONTROLAR `id_vehiculo` (solo la unidad de su reserva)."""
        r = self._por_token(token)
        if r is None:
            raise NoAutorizado("Tu reserva terminó o no es válida.")
        if r.id_vehiculo != id_vehiculo:
            raise Prohibido("Tu reserva es para otra unidad.")
        r.ultimo_latido = time.monotonic()                      # usar el mando también cuenta como señal
        return Actor(id_usuario=None, rol="invitado", via="invitado", id_sesion=r.id_sesion)

    def exigir_control(self, id_vehiculo, actor, es_paro=False):
        """Exclusividad: durante una reserva solo el invitado controla (DETENER siempre pasa)."""
        r = self.reserva_de(id_vehiculo)
        if actor.rol == "invitado":
            if r is None or r.id_sesion != actor.id_sesion:
                raise NoAutorizado("Tu reserva terminó.")
            return
        if r is not None and not es_paro:
            raise ConflictoNegocio(f"La unidad de exhibición está reservada por un visitante (termina en "
                                   f"{_mmss(r.segundos())}). DETENER sigue disponible.")

    def exigir_comando(self, id_vehiculo, id_comando=None, codigo=None):
        r = self.reserva_de(id_vehiculo)
        permitido = r is not None and any(
            (id_comando is not None and i == id_comando) or (codigo is not None and c["codigo"] == codigo)
            for i, c in r.comandos.items())
        if not permitido:
            raise Prohibido("Ese comando no está disponible para invitados en esta unidad.")

    def demos_permitidas(self, reserva):
        """DEMO de fábrica activas cuyos pasos son TODOS comandos permitidos y caben en el tiempo restante."""
        salida = []
        for d in self.demos.listar(reserva.id_vehiculo):
            if not d["activo"]:
                continue
            pasos = self.repositorio.obtener_movimientos_demo(d["id_demo"])
            if pasos and all(p["id_comando"] in reserva.comandos for p in pasos):
                duracion = sum(p["duracion_ms"] + p["pausa_ms"] for p in pasos)
                salida.append({"id_demo": d["id_demo"], "nombre": d["nombre"], "descripcion": d.get("descripcion"),
                               "pasos": len(pasos), "duracion_total_ms": duracion})
        return salida

    def exigir_demo(self, id_vehiculo, id_demo):
        r = self.reserva_de(id_vehiculo)
        demo = next((d for d in self.demos_permitidas(r) if d["id_demo"] == id_demo), None) if r else None
        if demo is None:
            raise Prohibido("Esa DEMO no está disponible para invitados.")
        if demo["duracion_total_ms"] > r.segundos() * 1000:
            raise ConflictoNegocio("No queda tiempo de reserva suficiente para esa DEMO.")

    # ------------------------------------------------------------ fin seguro

    async def finalizar(self, id_vehiculo, motivo):
        """Termina la reserva: cancela la DEMO, envía DETENER y la libera. Mejor esfuerzo en cada paso."""
        r = self._activas.pop(id_vehiculo, None)
        if r is None:
            return False
        await self.gestor.cerrar_si(
            id_vehiculo, lambda s: s.tipo == "invitado" and s.id_sesion == r.id_sesion, 4403, "Reserva terminada",
            eventos.error(id_vehiculo, "WS_REVOCADO", "Tu reserva terminó."))
        if self.demo_ejecutor.esta_ejecutando(id_vehiculo):
            try:
                await self.demo_ejecutor.cancelar(id_vehiculo)
            except Exception:
                logger.exception("No se pudo cancelar la DEMO del invitado en %s", id_vehiculo)
        try:
            detener = await asyncio.to_thread(self.comandos.buscar_detener, id_vehiculo)
            if detener is not None:
                resultado = await asyncio.to_thread(self.movimientos.registrar, id_vehiculo, None,
                                                    detener["codigo"], ORIGEN_SISTEMA, None)
                await self.gestor.difundir(id_vehiculo, eventos.movimiento_individual(resultado))
        except Exception:
            logger.exception("No se pudo enviar DETENER al terminar la reserva en %s", id_vehiculo)
        try:
            await asyncio.to_thread(self.repositorio.invitado_finalizar, r.id_reserva, motivo)
        except Exception:
            logger.exception("No se pudo cerrar la reserva %s en RDS", r.id_reserva)
        await asyncio.to_thread(self.auditoria.registrar, self._sistema(), "invitado.fin", "unidad", id_vehiculo,
                                {"id_reserva": r.id_reserva, "motivo": motivo})
        return True

    async def _vigilar(self):
        while True:
            await asyncio.sleep(VIGILANCIA_S)
            try:
                ahora_m = time.monotonic()
                for id_vehiculo, r in list(self._activas.items()):
                    if r.segundos() <= 0:
                        await self.finalizar(id_vehiculo, "expirada")
                    elif ahora_m - r.ultimo_latido > LATIDO_MAX_S:
                        await self.finalizar(id_vehiculo, "desconexion")
                for id_vehiculo in list(self._exhibicion):
                    if not self.exhibicion_abierta(id_vehiculo):
                        self._exhibicion.pop(id_vehiculo, None)
                        await self.finalizar(id_vehiculo, "admin")
            except Exception:
                logger.exception("Error en la vigilancia de reservas de invitado")

    async def iniciar(self):
        """Al arrancar: ninguna reserva de antes queda sin vigilancia; arranca el vigilante."""
        try:
            if self.esquema.tiene_invitados():
                cerradas = await asyncio.to_thread(self.repositorio.invitado_cerrar_todas, "detenida")
                if cerradas:
                    logger.info("Reservas de invitado cerradas al arrancar: %s", cerradas)
        except Exception:
            logger.exception("No se pudieron cerrar las reservas previas")
        self._tarea = asyncio.create_task(self._vigilar())

    async def cerrar(self):
        for id_vehiculo in list(self._activas):
            await self.finalizar(id_vehiculo, "detenida")
        if self._tarea is not None:
            self._tarea.cancel()

    # ------------------------------------------------------------ interruptor (empresa)

    def _exigir_unidad_exhibicion(self, id_vehiculo):
        unidad = self.repositorio.obtener_unidad(id_vehiculo)
        if unidad is None:
            raise RecursoNoEncontrado(f"La unidad {id_vehiculo} no existe.")
        if unidad["estado_comercial"] != "exhibicion" or not unidad["activo"]:
            raise ConflictoNegocio("Solo una unidad activa en estado «exhibición» se abre a invitados.")
        return unidad

    def estado_exhibicion(self, id_vehiculo):
        self.esquema.exigir_invitados()
        abierta = self._exhibicion.get(id_vehiculo) if self.exhibicion_abierta(id_vehiculo) else None
        r = self.reserva_de(id_vehiculo)
        return {
            "id_vehiculo": id_vehiculo, "abierta": abierta is not None,
            "abierta_hasta": abierta[0] if abierta else None,
            "reserva": None if r is None else {"id_reserva": r.id_reserva, "expira_en": r.expira,
                                                "segundos_restantes": r.segundos()},
        }

    async def cambiar_exhibicion(self, actor, id_vehiculo, abierta, horas):
        self._exigir()
        if abierta:
            if not 1 <= horas <= MAX_HORAS_EXHIBICION:
                raise SolicitudInvalida(f"La exhibición se abre de 1 a {MAX_HORAS_EXHIBICION} horas.")
            await asyncio.to_thread(self._exigir_unidad_exhibicion, id_vehiculo)
            self._exhibicion[id_vehiculo] = (_ahora() + timedelta(hours=horas), actor.id_usuario)
        else:
            self._exhibicion.pop(id_vehiculo, None)
            await self.finalizar(id_vehiculo, "admin")
        await asyncio.to_thread(self.auditoria.registrar, actor, "exhibicion.abrir" if abierta else "exhibicion.cerrar",
                                "unidad", id_vehiculo, {"horas": horas} if abierta else None)
        return self.estado_exhibicion(id_vehiculo)

    async def terminar_por_admin(self, actor, id_vehiculo):
        self.esquema.exigir_invitados()
        if not await self.finalizar(id_vehiculo, "admin"):
            raise ConflictoNegocio("Esa unidad no tiene una reserva de invitado en curso.")
        await asyncio.to_thread(self.auditoria.registrar, actor, "invitado.terminar", "unidad", id_vehiculo, None)
        return self.estado_exhibicion(id_vehiculo)
