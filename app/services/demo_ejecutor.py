"""Ejecución asíncrona de una DEMO por WebSocket.

DEMO = POST de inicio -> sp_obtener_movimientos_demo -> N eventos
ordenados y temporizados -> actualización de estado. NUNCA llama a
sp_registrar_historial.

El POST responde de inmediato (202) y la secuencia corre en una tarea
de asyncio; las esperas son asyncio (no bloquean a otros clientes) y las
llamadas a MySQL van a un hilo con asyncio.to_thread.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.core.exceptions import ConflictoNegocio
from app.websocket import eventos

logger = logging.getLogger(__name__)

SEGUNDOS_ESPERA_CANCELACION = 5


@dataclass
class DemoEnEjecucion:
    id_vehiculo: int
    id_demo: int
    nombre: str
    total: int
    iniciada_en: datetime
    cancelar: asyncio.Event = field(default_factory=asyncio.Event)
    tarea: Optional[asyncio.Task] = None
    movimientos_emitidos: int = 0
    orden_actual: Optional[int] = None


class DemoEjecutor:
    def __init__(self, demos, estados, comandos, gestor):
        self.demos = demos
        self.estados = estados
        self.comandos = comandos
        self.gestor = gestor
        self._activas = {}

    # ------------------------ consulta ------------------------

    def esta_ejecutando(self, id_vehiculo):
        return id_vehiculo in self._activas

    def estado(self, id_vehiculo):
        ejecucion = self._activas.get(id_vehiculo)

        if ejecucion is None:
            return {"en_ejecucion": False}

        return {
            "en_ejecucion": True,
            "id_demo": ejecucion.id_demo,
            "nombre": ejecucion.nombre,
            "movimientos_emitidos": ejecucion.movimientos_emitidos,
            "total_movimientos": ejecucion.total,
            "orden_actual": ejecucion.orden_actual,
            "iniciada_en": ejecucion.iniciada_en,
            "cancelacion_solicitada": ejecucion.cancelar.is_set(),
        }

    # ------------------------ control ------------------------

    async def iniciar(self, id_vehiculo, id_demo):
        # Validaciones y lectura de RDS (bloqueante -> hilo).
        demo, movimientos = await asyncio.to_thread(
            self.demos.preparar_ejecucion, id_vehiculo, id_demo
        )

        # Desde aquí hasta registrar la tarea NO hay 'await': la
        # comprobación y el registro son atómicos y es imposible que dos
        # POST simultáneos arranquen dos DEMO en el mismo vehículo.
        if id_vehiculo in self._activas:
            raise ConflictoNegocio(
                f"El vehículo {id_vehiculo} ya está ejecutando una DEMO. "
                "Cancélala antes de iniciar otra."
            )

        ejecucion = DemoEnEjecucion(
            id_vehiculo=id_vehiculo,
            id_demo=id_demo,
            nombre=demo["nombre"],
            total=len(movimientos),
            iniciada_en=datetime.now(timezone.utc),
        )
        self._activas[id_vehiculo] = ejecucion
        ejecucion.tarea = asyncio.create_task(
            self._ejecutar(ejecucion, demo, movimientos)
        )

        duracion = sum(
            m["duracion_ms"] + m["pausa_ms"] for m in movimientos
        )
        return {
            "id_vehiculo": id_vehiculo,
            "id_demo": id_demo,
            "nombre": demo["nombre"],
            "total_movimientos": len(movimientos),
            "duracion_estimada_ms": duracion,
            "clientes_websocket": self.gestor.total_clientes(id_vehiculo),
            "mensaje": (
                "DEMO aceptada. Los movimientos se transmiten por "
                f"WebSocket (/ws/vehiculos/{id_vehiculo})."
            ),
        }

    async def cancelar(self, id_vehiculo):
        ejecucion = self._activas.get(id_vehiculo)

        if ejecucion is None:
            raise ConflictoNegocio(
                f"El vehículo {id_vehiculo} no tiene una DEMO en ejecución."
            )

        # La cancelación tiene prioridad: la tarea revisa esta bandera
        # antes de cada movimiento y en cada espera.
        ejecucion.cancelar.set()

        if ejecucion.tarea is not None:
            await asyncio.wait(
                {ejecucion.tarea}, timeout=SEGUNDOS_ESPERA_CANCELACION
            )

        return {
            "id_vehiculo": id_vehiculo,
            "id_demo": ejecucion.id_demo,
            "movimientos_emitidos": ejecucion.movimientos_emitidos,
            "mensaje": (
                "Cancelación aplicada: no se emitirán más movimientos."
            ),
        }

    async def cerrar(self):
        """Al apagar el servidor: cancela todas las DEMO en curso."""

        tareas = []

        for ejecucion in list(self._activas.values()):
            ejecucion.cancelar.set()

            if ejecucion.tarea is not None:
                tareas.append(ejecucion.tarea)

        if tareas:
            await asyncio.wait(tareas, timeout=SEGUNDOS_ESPERA_CANCELACION)

    # ------------------------ ejecución ------------------------

    async def _emitir(self, id_vehiculo, mensaje):
        await self.gestor.difundir(id_vehiculo, mensaje)

    async def _esperar(self, ejecucion, milisegundos):
        """Duerme ms milisegundos. Devuelve True si se canceló la DEMO."""

        if milisegundos <= 0:
            return ejecucion.cancelar.is_set()

        try:
            await asyncio.wait_for(
                ejecucion.cancelar.wait(), timeout=milisegundos / 1000
            )
            return True
        except asyncio.TimeoutError:
            return False

    async def _detener_seguro(self, id_vehiculo):
        """Finalización segura: deja el estado en DETENER (si existe).

        Es un mejor esfuerzo: si RDS falla no se propaga el error.
        """

        try:
            detener = await asyncio.to_thread(
                self.comandos.buscar_detener, id_vehiculo
            )

            if detener is not None:
                await asyncio.to_thread(
                    self.estados.fijar_comando,
                    id_vehiculo, detener["id_comando"],
                )

            return detener
        except Exception:
            logger.exception(
                "No fue posible dejar el vehículo %s en DETENER.", id_vehiculo
            )
            return None

    async def _ejecutar(self, ejecucion, demo, movimientos):
        id_vehiculo = ejecucion.id_vehiculo
        id_demo = ejecucion.id_demo
        total = len(movimientos)
        resultado = "finalizada"

        try:
            await self._emitir(id_vehiculo, eventos.demo_iniciada(
                id_vehiculo, demo, total,
                sum(m["duracion_ms"] + m["pausa_ms"] for m in movimientos),
            ))

            for movimiento in movimientos:  # ya vienen ordenados por 'orden'
                if ejecucion.cancelar.is_set():
                    resultado = "cancelada"
                    break

                # 1) Persistir el último comando (SIN historial).
                await asyncio.to_thread(
                    self.estados.fijar_comando,
                    id_vehiculo, movimiento["id_comando"],
                )

                # La cancelación tiene prioridad sobre la emisión.
                if ejecucion.cancelar.is_set():
                    resultado = "cancelada"
                    break

                # 2) Notificar el movimiento.
                ejecucion.orden_actual = movimiento["orden"]
                await self._emitir(id_vehiculo, eventos.demo_movimiento(
                    id_vehiculo, id_demo, movimiento, total,
                ))
                ejecucion.movimientos_emitidos += 1

                # 3) Respetar duracion_ms y pausa_ms.
                if await self._esperar(ejecucion, movimiento["duracion_ms"]):
                    resultado = "cancelada"
                    break

                if await self._esperar(ejecucion, movimiento["pausa_ms"]):
                    resultado = "cancelada"
                    break

        except asyncio.CancelledError:
            # Apagado del servidor: salir sin más trabajo.
            self._activas.pop(id_vehiculo, None)
            raise

        except Exception:
            # Falla de RDS, de datos o de red: terminar de forma controlada.
            logger.exception("Falla durante la DEMO %s.", id_demo)
            resultado = "error"

        try:
            if resultado == "finalizada":
                await self._cerrar_normal(ejecucion, movimientos)
            elif resultado == "cancelada":
                detener = await self._detener_seguro(id_vehiculo)
                await self._emitir(id_vehiculo, eventos.demo_cancelada(
                    id_vehiculo, id_demo,
                    ejecucion.movimientos_emitidos, detener,
                ))
            else:
                await self._detener_seguro(id_vehiculo)
                await self._emitir(id_vehiculo, eventos.error(
                    id_vehiculo, "DEMO_ERROR",
                    "La DEMO se detuvo por un error interno.", id_demo,
                ))
        except Exception:
            logger.exception("No fue posible notificar el cierre de la DEMO.")
        finally:
            self._activas.pop(id_vehiculo, None)

    async def _cerrar_normal(self, ejecucion, movimientos):
        id_vehiculo = ejecucion.id_vehiculo

        # Si el último movimiento no fue DETENER, dejar el vehículo detenido.
        if str(movimientos[-1]["comando"]).upper() != "DETENER":
            await self._detener_seguro(id_vehiculo)

        await self._emitir(id_vehiculo, eventos.demo_finalizada(
            id_vehiculo, ejecucion.id_demo, ejecucion.movimientos_emitidos,
        ))
