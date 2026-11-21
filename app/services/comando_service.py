import asyncio

from app.core.exceptions import ConflictoNegocio, RecursoNoEncontrado
from app.websocket import eventos


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
                f"El movimiento {comando['nombre']} está bloqueado en esta unidad."
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


class BloqueoComandos:
    """La EMPRESA (administrador) bloquea o desbloquea movimientos de CUALQUIER unidad.

    No necesita la autorización de soporte del comprador: la empresa es la dueña
    inicial del producto y puede retirar un movimiento por seguridad o garantía.
    Bloquear = marcar el comando inactivo en el catálogo de la unidad (sin migración):
    la API rechaza ese movimiento a todos (cliente, invitado, DEMO) y la página de
    Control lo deshabilita. DETENER nunca se bloquea (es la parada de seguridad).
    El cliente NO puede desbloquearlo (editar el catálogo es solo del administrador).
    """

    def __init__(self, repositorio, comandos, auditoria, demo_ejecutor, invitados, gestor):
        self.repositorio = repositorio
        self.comandos = comandos
        self.auditoria = auditoria
        self.demo_ejecutor = demo_ejecutor
        self.invitados = invitados
        self.gestor = gestor

    async def cambiar(self, actor, id_vehiculo, id_comando, bloqueado):
        await asyncio.to_thread(self.comandos.vehiculos.obtener_o_fallar, id_vehiculo)
        comando = await asyncio.to_thread(self.comandos.obtener_en_catalogo, id_vehiculo, id_comando)
        if bloqueado and comando["nombre"].upper() == "DETENER":
            raise ConflictoNegocio("DETENER no se puede bloquear: es la parada de seguridad de la unidad.")

        if bool(comando["activo"]) == (not bloqueado):
            return comando                                  # ya estaba así: nada que hacer

        await asyncio.to_thread(
            self.repositorio.actualizar_comando, id_comando, comando["nombre"], comando["codigo"],
            comando.get("descripcion"), not bloqueado,
        )
        comando = await asyncio.to_thread(self.comandos.obtener_en_catalogo, id_vehiculo, id_comando)

        demo_cancelada = False
        if bloqueado and self.demo_ejecutor.esta_ejecutando(id_vehiculo):
            # Una DEMO en curso que usa ese movimiento se detiene ya (termina en DETENER).
            id_demo = self.demo_ejecutor.estado(id_vehiculo).get("id_demo")
            pasos = await asyncio.to_thread(self.repositorio.obtener_movimientos_demo, id_demo) if id_demo else []
            if any(p["id_comando"] == id_comando for p in pasos):
                try:
                    await self.demo_ejecutor.cancelar(id_vehiculo)
                    demo_cancelada = True
                except ConflictoNegocio:
                    pass                                    # terminó justo antes

        await asyncio.to_thread(self.invitados.refrescar_comandos, id_vehiculo)
        await asyncio.to_thread(
            self.auditoria.registrar, actor, "comando.bloquear" if bloqueado else "comando.desbloquear",
            "unidad", id_vehiculo,
            {"id_comando": id_comando, "comando": comando["nombre"], "codigo": comando["codigo"],
             "demo_cancelada": demo_cancelada},
        )
        await self.gestor.difundir(id_vehiculo, eventos.construir(
            eventos.CATALOGO_ACTUALIZADO, id_vehiculo, comando["nombre"], comando["codigo"],
            {"id_comando": id_comando, "bloqueado": bloqueado,
             "mensaje": f"La empresa {'bloqueó' if bloqueado else 'desbloqueó'} el movimiento {comando['nombre']}."},
        ))
        return comando
