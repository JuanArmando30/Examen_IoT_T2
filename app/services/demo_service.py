"""DEMO y sus N movimientos configurables.

- DEMO de FÁBRICA (ambito='fabrica'): las gestiona la empresa; las ve
  cualquiera que pueda ver la unidad y se inician desde Control.
- DEMO PRIVADAS (ambito='privada', V004/V011): las crea el comprador en SU
  unidad. Solo él las ve, edita e inicia; nunca salen por las rutas públicas
  ni por las del catálogo técnico (aunque el SP original devuelva todas).
- Límites de seguridad del modelo (V011): duración y pausa de cada paso,
  número de pasos y duración total. Se validan al GUARDAR y otra vez al
  INICIAR (el firmware no pone tope a la duración que recibe: hallazgo H9).
"""

import json

from app.core.exceptions import ConflictoNegocio, Prohibido, RecursoNoEncontrado, SolicitudInvalida

FABRICA = "fabrica"
PRIVADA = "privada"


def es_privada(demo):
    return demo.get("ambito") == PRIVADA


class DemoService:
    def __init__(self, repositorio, vehiculos, comandos, esquema=None, auditoria=None):
        self.repositorio = repositorio
        self.vehiculos = vehiculos
        self.comandos = comandos
        self.esquema = esquema
        self.auditoria = auditoria
        self.ejecutor = None            # lo asigna el contenedor (evita la dependencia circular)

    # ------------------------- utilidades -------------------------

    def _con_v011(self):
        return self.esquema is not None and self.esquema.tiene_demos_privadas()

    def _auditar(self, actor, accion, id_demo, detalle=None):
        if self.auditoria is not None and actor is not None:
            self.auditoria.registrar(actor, accion, "demo", id_demo, detalle)

    def _en_ejecucion(self, id_vehiculo, id_demo):
        if self.ejecutor is None or not self.ejecutor.esta_ejecutando(id_vehiculo):
            return False
        return self.ejecutor.estado(id_vehiculo).get("id_demo") == id_demo

    def limites(self, id_vehiculo):
        """Límites del modelo de la unidad (None si la base aún no tiene V011)."""
        if not self._con_v011():
            return None
        limites = self.repositorio.limites_unidad(id_vehiculo)
        if limites is None:
            raise RecursoNoEncontrado(f"El vehículo {id_vehiculo} no existe.")
        return limites

    def validar_limites(self, id_vehiculo, pasos):
        """`pasos`: lista de dicts con duracion_ms y pausa_ms. 400 si excede el modelo."""
        lim = self.limites(id_vehiculo)
        if lim is None:
            return
        maximo = lim["max_paso_ms"]
        if len(pasos) > lim["max_pasos_demo"]:
            raise SolicitudInvalida(f"La DEMO admite como máximo {lim['max_pasos_demo']} pasos en este modelo.")
        for i, p in enumerate(pasos, start=1):
            if not 1 <= p["duracion_ms"] <= maximo or not 0 <= p.get("pausa_ms", 0) <= maximo:
                raise SolicitudInvalida(
                    f"Paso {i}: la duración debe estar entre 1 y {maximo} ms y la pausa entre 0 y {maximo} ms.")
        total = sum(p["duracion_ms"] + p.get("pausa_ms", 0) for p in pasos)
        if total > lim["max_demo_ms"]:
            raise SolicitudInvalida(
                f"La DEMO completa dura {total} ms y el máximo de este modelo es {lim['max_demo_ms']} ms.")

    # ------------------------- DEMO (rutas públicas y técnicas) -------------------------

    def listar(self, id_vehiculo):
        """Solo DEMO de fábrica: las privadas nunca salen por aquí."""
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        return [d for d in self.repositorio.obtener_demos(id_vehiculo) if not es_privada(d)]

    def obtener_de_vehiculo(self, id_vehiculo, id_demo, actor=None):
        """La DEMO debe existir y ser de ese vehículo. Una privada solo la «ve» su dueño
        (para cualquier otro es como si no existiera: 404, sin revelar que existe)."""
        for demo in self.repositorio.obtener_demos(id_vehiculo):
            if demo["id_demo"] == id_demo:
                if es_privada(demo) and (actor is None or actor.id_usuario != demo.get("id_propietario")):
                    break
                return demo
        raise RecursoNoEncontrado(f"La DEMO {id_demo} no existe en el vehículo {id_vehiculo}.")

    def crear(self, id_vehiculo, nombre, descripcion):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        id_demo = self.repositorio.crear_demo(id_vehiculo, nombre, descripcion)
        return self.obtener_de_vehiculo(id_vehiculo, id_demo)

    def actualizar(self, id_vehiculo, id_demo, nombre, descripcion, activo):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        self.obtener_de_vehiculo(id_vehiculo, id_demo)
        self.repositorio.actualizar_demo(id_demo, nombre, descripcion, activo)
        return self.obtener_de_vehiculo(id_vehiculo, id_demo)

    def eliminar(self, id_vehiculo, id_demo):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        self.obtener_de_vehiculo(id_vehiculo, id_demo)
        if self._en_ejecucion(id_vehiculo, id_demo):
            raise ConflictoNegocio("La DEMO está en ejecución. Cancélala antes de eliminarla.")
        self.repositorio.eliminar_demo(id_demo)

    # ------------------- MOVIMIENTOS DE DEMO (rutas técnicas) -------------------

    def movimientos(self, id_vehiculo, id_demo, actor=None):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        self.obtener_de_vehiculo(id_vehiculo, id_demo, actor)
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
        actuales = self.repositorio.obtener_movimientos_demo(id_demo)
        self.validar_limites(id_vehiculo, actuales + [{"duracion_ms": duracion_ms, "pausa_ms": pausa_ms}])

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
        nuevos = [m if m["id_demo_movimiento"] != id_movimiento else {"duracion_ms": duracion_ms, "pausa_ms": pausa_ms}
                  for m in self.repositorio.obtener_movimientos_demo(id_demo)]
        self.validar_limites(id_vehiculo, nuevos)

        self.repositorio.actualizar_movimiento_demo(
            id_movimiento, id_comando, orden, duracion_ms, pausa_ms
        )
        return self._obtener_movimiento(id_demo, id_movimiento)

    def eliminar_movimiento(self, id_vehiculo, id_demo, id_movimiento):
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        self.obtener_de_vehiculo(id_vehiculo, id_demo)
        self._obtener_movimiento(id_demo, id_movimiento)
        self.repositorio.eliminar_movimiento_demo(id_movimiento)

    # ------------------------- EDITOR (V011) -------------------------

    def _resumen(self, demo, actor):
        pasos = self.repositorio.obtener_movimientos_demo(demo["id_demo"])
        propia = es_privada(demo) and actor is not None and actor.id_usuario == demo.get("id_propietario")
        return {
            "id_demo": demo["id_demo"], "id_vehiculo": demo["id_vehiculo"],
            "nombre": demo["nombre"], "descripcion": demo.get("descripcion"), "activo": bool(demo["activo"]),
            "ambito": PRIVADA if es_privada(demo) else FABRICA, "propia": propia,
            "pasos": len(pasos), "duracion_total_ms": sum(m["duracion_ms"] + m["pausa_ms"] for m in pasos),
        }

    def visibles(self, id_vehiculo, actor):
        """DEMO de fábrica + las privadas del usuario en esa unidad."""
        self.esquema.exigir_demos_privadas()
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        demos = [d for d in self.repositorio.obtener_demos(id_vehiculo)
                 if not es_privada(d) or d.get("id_propietario") == actor.id_usuario]
        return [self._resumen(d, actor) for d in demos]

    def detalle(self, id_vehiculo, id_demo, actor):
        self.esquema.exigir_demos_privadas()
        demo = self.obtener_de_vehiculo(id_vehiculo, id_demo, actor)
        return {**self._resumen(demo, actor), "movimientos": self.repositorio.obtener_movimientos_demo(id_demo)}

    def _exigir_propia(self, id_vehiculo, id_demo, actor):
        demo = self.obtener_de_vehiculo(id_vehiculo, id_demo, actor)
        if not es_privada(demo):
            raise Prohibido("Las DEMO de fábrica las edita la empresa. Puedes usarlas o crear una propia.")
        return demo

    def crear_privada(self, actor, id_vehiculo, nombre, descripcion):
        self.esquema.exigir_demos_privadas()
        self.vehiculos.obtener_o_fallar(id_vehiculo)
        id_demo = self.repositorio.crear_demo_privada(id_vehiculo, actor.id_usuario, nombre.strip(), descripcion)
        self._auditar(actor, "demo.crear", id_demo, {"id_vehiculo": id_vehiculo, "nombre": nombre.strip(), "ambito": PRIVADA})
        return self.detalle(id_vehiculo, id_demo, actor)

    def actualizar_privada(self, actor, id_vehiculo, id_demo, nombre, descripcion, activo):
        self.esquema.exigir_demos_privadas()
        self._exigir_propia(id_vehiculo, id_demo, actor)
        self.repositorio.actualizar_demo(id_demo, nombre.strip(), descripcion, activo)
        self._auditar(actor, "demo.actualizar", id_demo, {"nombre": nombre.strip(), "activo": activo})
        return self.detalle(id_vehiculo, id_demo, actor)

    def eliminar_privada(self, actor, id_vehiculo, id_demo):
        self.esquema.exigir_demos_privadas()
        demo = self._exigir_propia(id_vehiculo, id_demo, actor)
        if self._en_ejecucion(id_vehiculo, id_demo):
            raise ConflictoNegocio("La DEMO está en ejecución. Detenla antes de eliminarla.")
        self.repositorio.eliminar_demo(id_demo)
        self._auditar(actor, "demo.eliminar", id_demo, {"nombre": demo["nombre"]})

    def guardar_pasos(self, actor, id_vehiculo, id_demo, pasos, ambito):
        """Reemplaza TODOS los pasos (el orden es el de la lista).

        ambito=PRIVADA: la DEMO debe ser del usuario. ambito=FABRICA: DEMO de fábrica
        (lo usa el administrador)."""
        self.esquema.exigir_demos_privadas()
        demo = self.obtener_de_vehiculo(id_vehiculo, id_demo, actor)
        if (ambito == PRIVADA) != es_privada(demo):
            raise Prohibido("Esta DEMO no se puede editar desde aquí.")
        if self._en_ejecucion(id_vehiculo, id_demo):
            raise ConflictoNegocio("La DEMO está en ejecución. Detenla antes de cambiar sus pasos.")

        catalogo = {c["id_comando"]: c for c in self.repositorio.obtener_comandos_vehiculo(id_vehiculo)}
        for i, p in enumerate(pasos, start=1):
            c = catalogo.get(p["id_comando"])
            if c is None or not c["activo"]:
                raise SolicitudInvalida(f"Paso {i}: el comando no existe en esta unidad o está inactivo.")
        self.validar_limites(id_vehiculo, pasos)

        r = self.repositorio.guardar_pasos_demo(id_demo, json.dumps(
            [{"id_comando": p["id_comando"], "duracion_ms": p["duracion_ms"], "pausa_ms": p.get("pausa_ms", 0)} for p in pasos]))
        self._auditar(actor, "demo.pasos", id_demo, {"pasos": r["pasos"], "duracion_total_ms": r["duracion_total_ms"], "ambito": ambito})
        return self.detalle(id_vehiculo, id_demo, actor)

    # --------------------- EJECUCIÓN ---------------------

    def preparar_ejecucion(self, id_vehiculo, id_demo, actor=None):
        """Valida todo ANTES de arrancar y devuelve (demo, movimientos).

        Los N movimientos se leen de RDS con sp_obtener_movimientos_demo:
        no existe ninguna secuencia fija en el código. Una DEMO privada solo
        la inicia su dueño; con V011 se exigen los límites del modelo.
        """

        self.vehiculos.exigir_activo(id_vehiculo)
        demo = self.obtener_de_vehiculo(id_vehiculo, id_demo, actor)

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

        try:
            self.validar_limites(id_vehiculo, movimientos)
        except SolicitudInvalida as error:
            raise ConflictoNegocio(f"La DEMO excede los límites de seguridad del modelo: {error.mensaje}") from error

        return demo, movimientos
