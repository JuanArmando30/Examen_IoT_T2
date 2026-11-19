"""Inicio de sesión, tokens y autorización por unidad (Etapa 4).

Reglas (ver docs/administracion/04-autenticacion.md):
- Login con correo + contraseña (Argon2id). Mensaje genérico ante error:
  no revela si el correo existe. 5 fallos → bloqueo de 15 min (en la base)
  y además límite de tasa por IP y por correo (en memoria).
- Acceso: JWT de 10 min. Renovación: token opaco que ROTA en cada uso; si se
  presenta uno ya usado, se revoca toda la familia (posible robo).
- En cada petición se relee el usuario de la base: desactivar una cuenta o
  cambiarle el rol tiene efecto inmediato aunque su JWT siga vigente.
- Autorización por unidad (BOLA/IDOR): el comprador solo opera SUS unidades;
  el administrador opera unidades en inventario/exhibición y una vendida
  solo con autorización de soporte vigente del comprador.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from app.core import contrasenas, tokens
from app.core.exceptions import (
    ConflictoNegocio,
    DemasiadosIntentos,
    NoAutorizado,
    NoConfigurado,
    Prohibido,
    RecursoNoEncontrado,
    SolicitudInvalida,
)
from app.core.limite import LimitadorTasa
from app.services.administracion import Actor

logger = logging.getLogger(__name__)

ROL_ADMIN = "admin"
ROL_USUARIO = "usuario"
MENSAJE_LOGIN = "Correo o contraseña incorrectos."
MENSAJE_SESION = "La sesión ya no es válida. Inicia sesión de nuevo."
MENSAJE_CODIGO = ("Código inválido, vencido o agotado. Si es necesario, pide uno nuevo "
                  "al administrador.")
MAX_HORAS_SOPORTE = 72


@dataclass(frozen=True)
class Principal:
    """Usuario autenticado con token (datos releídos de la base)."""

    id_usuario: int
    rol: str
    nombre: str
    correo: str
    debe_cambiar_contrasena: bool = False

    @property
    def es_admin(self):
        return self.rol == ROL_ADMIN

    def actor(self):
        return Actor(id_usuario=self.id_usuario, rol=self.rol, via="token")


def _utc_sin_zona(momento):
    """MySQL DATETIME sin zona: la base trabaja en UTC (UTC_TIMESTAMP)."""
    return momento.replace(tzinfo=None)


def _agente(agente):
    return (agente or "")[:120] or None


class AuthService:
    def __init__(self, repositorio, esquema, auditoria, usuarios, auth):
        self.repositorio = repositorio
        self.esquema = esquema
        self.auditoria = auditoria
        self.usuarios = usuarios
        self.auth = auth
        # Límites en memoria (un solo proceso de Uvicorn).
        self.limite_login_ip = LimitadorTasa(20, 300)
        self.limite_login_correo = LimitadorTasa(10, 900)
        self.limite_codigo_ip = LimitadorTasa(10, 900)
        self.limite_codigo_correo = LimitadorTasa(6, 900)
        self.limite_renovar_ip = LimitadorTasa(60, 300)
        self.limite_cambio = LimitadorTasa(5, 900)

    # ------------------------------------------------------------ utilidades

    def _exigir(self):
        if not self.auth.configurado:
            raise NoConfigurado()
        self.esquema.exigir_autenticacion()

    def _auditar(self, actor, accion, recurso_id=None, detalle=None, resultado="ok"):
        self.auditoria.registrar(actor, accion, "usuario", recurso_id, detalle, resultado)

    @staticmethod
    def _sistema():
        return Actor(id_usuario=None, rol="sistema", via="auth")

    def _sesion(self, usuario, familia, agente):
        """Emite acceso + renovación (la renovación se guarda como HMAC)."""
        acceso, expira_acceso = tokens.emitir_acceso(self.auth, usuario)
        renovacion = tokens.secreto_aleatorio()
        expira_renovacion = tokens.ahora() + timedelta(days=self.auth.renovacion_dias)
        self.repositorio.token_crear(
            usuario["id_usuario"], tokens.huella(self.auth, renovacion), familia,
            _utc_sin_zona(expira_renovacion), _agente(agente),
        )
        return self._respuesta(usuario, acceso, expira_acceso, renovacion, expira_renovacion)

    def _respuesta(self, usuario, acceso, expira_acceso, renovacion, expira_renovacion):
        return {
            "token_acceso": acceso,
            "tipo": "Bearer",
            "expira_en": self.auth.acceso_min * 60,
            "acceso_expira": expira_acceso,
            "token_renovacion": renovacion,
            "renovacion_expira": expira_renovacion,
            "usuario": {
                "id_usuario": usuario["id_usuario"],
                "correo": usuario["correo"],
                "nombre": usuario["nombre"],
                "rol": usuario["rol"],
                "debe_cambiar_contrasena": bool(usuario.get("debe_cambiar_contrasena")),
            },
        }

    # ------------------------------------------------------------ sesión

    def login(self, correo, contrasena, ip, agente=None):
        self._exigir()
        correo = (correo or "").strip().lower()
        self.limite_login_ip.registrar(ip)
        self.limite_login_correo.registrar(correo)

        fila = self.repositorio.login_obtener(correo) if correo else None
        if fila is None:
            contrasenas.igualar_tiempo(contrasena)
            self._auditar(self._sistema(), "login.fallo", None, {"motivo": "credenciales"}, "rechazado")
            raise NoAutorizado(MENSAJE_LOGIN)

        if fila["bloqueado"]:
            contrasenas.igualar_tiempo(contrasena)
            self._auditar(self._sistema(), "login.bloqueado", fila["id_usuario"], None, "rechazado")
            raise DemasiadosIntentos(
                f"Demasiados intentos fallidos. Vuelve a probar en {self.auth.bloqueo_min} minutos "
                "o pide un código de restablecimiento al administrador."
            )

        correcta = contrasenas.verificar(fila["hash_contrasena"], contrasena)
        if not correcta or not fila["activo"]:
            if fila["activo"]:
                self.repositorio.login_resultado(fila["id_usuario"], False,
                                                 self.auth.max_intentos_login, self.auth.bloqueo_min)
            self._auditar(self._sistema(), "login.fallo", fila["id_usuario"],
                          {"motivo": "inactivo" if correcta else "credenciales"}, "rechazado")
            raise NoAutorizado(MENSAJE_LOGIN)

        self.repositorio.login_resultado(fila["id_usuario"], True,
                                         self.auth.max_intentos_login, self.auth.bloqueo_min)
        actor = Actor(fila["id_usuario"], fila["rol"], "token")
        self._auditar(actor, "login.ok", fila["id_usuario"])
        return self._sesion(fila, tokens.familia_nueva(), agente)

    def renovar(self, token_renovacion, ip, agente=None):
        self._exigir()
        self.limite_renovar_ip.registrar(ip)
        if not token_renovacion:
            raise NoAutorizado(MENSAJE_SESION)
        nuevo = tokens.secreto_aleatorio()
        expira = tokens.ahora() + timedelta(days=self.auth.renovacion_dias)
        r = self.repositorio.token_usar(
            tokens.huella(self.auth, token_renovacion), tokens.huella(self.auth, nuevo),
            _utc_sin_zona(expira), _agente(agente),
        )
        if r.get("resultado") != "ok":
            if r.get("resultado") == "reutilizado":
                logger.warning("Token de renovación reutilizado: se revocó la familia.")
                self._auditar(self._sistema(), "sesion.reutilizacion", None, None, "rechazado")
            raise NoAutorizado(MENSAJE_SESION)
        acceso, expira_acceso = tokens.emitir_acceso(self.auth, r)
        return self._respuesta(r, acceso, expira_acceso, nuevo, expira)

    def salir(self, token_renovacion):
        """Revoca la familia del token. Siempre responde bien (no revela nada)."""
        self._exigir()
        if token_renovacion:
            self.repositorio.token_revocar(tokens.huella(self.auth, token_renovacion))

    def principal_desde_token(self, token):
        if not self.auth.configurado or not self.esquema.tiene_autenticacion():
            raise NoAutorizado("El inicio de sesión aún no está disponible en el servidor.")
        datos = tokens.verificar_acceso(self.auth, token)
        try:
            id_usuario = int(datos["sub"])
        except (TypeError, ValueError) as error:
            raise NoAutorizado("Token de acceso inválido.") from error
        usuario = self.repositorio.obtener_usuario_auth(id_usuario)
        if usuario is None or not usuario["activo"]:
            raise NoAutorizado(MENSAJE_SESION)
        return Principal(
            id_usuario=usuario["id_usuario"], rol=usuario["rol"], nombre=usuario["nombre"],
            correo=usuario["correo"],
            debe_cambiar_contrasena=bool(usuario.get("debe_cambiar_contrasena")),
        )

    # ------------------------------------------------------------ contraseñas

    def generar_codigo(self, actor, id_usuario):
        """El administrador genera un código de un solo uso y se lo entrega al usuario."""
        self._exigir()
        usuario = self.usuarios.obtener_o_fallar(id_usuario)
        if not usuario["activo"]:
            raise ConflictoNegocio("El usuario está desactivado: actívalo antes de generar un código.")
        codigo = tokens.codigo_restablecimiento()
        expira = tokens.ahora() + timedelta(minutes=self.auth.codigo_min)
        self.repositorio.codigo_crear(
            id_usuario, tokens.huella(self.auth, tokens.normalizar_codigo(codigo)),
            actor.id_usuario, _utc_sin_zona(expira),
        )
        self._auditar(actor, "usuario.codigo_restablecimiento", id_usuario,
                      {"correo": usuario["correo"], "minutos": self.auth.codigo_min})
        return {"id_usuario": id_usuario, "correo": usuario["correo"], "codigo": codigo,
                "expira_en": expira, "minutos": self.auth.codigo_min}

    def restablecer(self, correo, codigo, contrasena_nueva, ip):
        self._exigir()
        correo = (correo or "").strip().lower()
        self.limite_codigo_ip.registrar(ip)
        self.limite_codigo_correo.registrar(correo)
        contrasenas.validar_politica(contrasena_nueva, correo)
        r = self.repositorio.codigo_usar(
            correo, tokens.huella(self.auth, tokens.normalizar_codigo(codigo)),
            contrasenas.hashear(contrasena_nueva), self.auth.max_intentos_codigo,
        )
        if r.get("resultado") != "ok":
            self._auditar(self._sistema(), "contrasena.restablecer", None,
                          {"resultado": r.get("resultado")}, "rechazado")
            raise SolicitudInvalida(MENSAJE_CODIGO)
        self._auditar(self._sistema(), "contrasena.restablecer", r.get("id_usuario"))
        return {"mensaje": "Contraseña actualizada. Ya puedes iniciar sesión."}

    def cambiar_contrasena(self, principal, actual, nueva, agente=None):
        """Cambia la contraseña, cierra las demás sesiones y devuelve una sesión nueva."""
        self._exigir()
        self.limite_cambio.registrar(principal.id_usuario)
        fila = self.repositorio.login_obtener(principal.correo)
        if fila is None or not contrasenas.verificar(fila["hash_contrasena"], actual):
            raise SolicitudInvalida("La contraseña actual no es correcta.")
        if actual == nueva:
            raise SolicitudInvalida("La contraseña nueva debe ser distinta de la actual.")
        contrasenas.validar_politica(nueva, principal.correo)
        self.repositorio.cambiar_contrasena(principal.id_usuario, contrasenas.hashear(nueva))
        self._auditar(principal.actor(), "contrasena.cambiar", principal.id_usuario)
        usuario = self.repositorio.obtener_usuario_auth(principal.id_usuario)
        return self._sesion(usuario, tokens.familia_nueva(), agente)

    # ------------------------------------------------------------ autorización por unidad

    def relacion(self, principal, id_vehiculo):
        self.esquema.exigir_autenticacion()
        rel = self.repositorio.acceso_unidad(principal.id_usuario, id_vehiculo)
        if rel is None:
            raise RecursoNoEncontrado(f"El vehículo {id_vehiculo} no existe.")
        return rel

    def exigir_acceso_unidad(self, principal, id_vehiculo):
        """Decide si el usuario del token puede ver/operar la unidad.

        - usuario: solo si es el propietario vigente.
        - admin: inventario/exhibición sí; vendida solo con soporte vigente; baja no.
        """
        rel = self.relacion(principal, id_vehiculo)
        if principal.rol == ROL_USUARIO:
            if not rel["es_propietario"]:
                raise Prohibido("Esta unidad no está asignada a tu cuenta.")
            return rel
        if principal.rol == ROL_ADMIN:
            estado = rel["estado_comercial"]
            if estado in ("inventario", "exhibicion"):
                return rel
            if estado == "vendida":
                if rel["soporte_vigente"]:
                    return rel
                raise Prohibido("La unidad pertenece a un cliente: necesitas su autorización de "
                                "soporte vigente para operarla.")
            raise Prohibido("La unidad está dada de baja.")
        raise Prohibido()

    # ------------------------------------------------------------ comprador

    def mis_vehiculos(self, principal):
        self.esquema.exigir_autenticacion()
        return self.repositorio.mis_vehiculos(principal.id_usuario)

    def _exigir_propietario(self, principal, id_vehiculo):
        rel = self.relacion(principal, id_vehiculo)
        if not rel["es_propietario"]:
            raise Prohibido("Esta unidad no está asignada a tu cuenta.")

    def soporte_listar(self, principal, id_vehiculo):
        if not principal.es_admin:
            self._exigir_propietario(principal, id_vehiculo)
        else:
            self.relacion(principal, id_vehiculo)
        return self.repositorio.soporte_listar(id_vehiculo)

    def soporte_otorgar(self, principal, id_vehiculo, horas, motivo, id_administrador=None):
        self._exigir_propietario(principal, id_vehiculo)
        if not 1 <= horas <= MAX_HORAS_SOPORTE:
            raise SolicitudInvalida(f"La autorización dura entre 1 y {MAX_HORAS_SOPORTE} horas.")
        expira = tokens.ahora() + timedelta(hours=horas)
        id_autorizacion = self.repositorio.soporte_otorgar(
            id_vehiculo, principal.id_usuario, id_administrador, (motivo or "").strip() or None,
            _utc_sin_zona(expira),
        )
        self.auditoria.registrar(principal.actor(), "soporte.otorgar", "unidad", id_vehiculo,
                                 {"id_autorizacion": id_autorizacion, "horas": horas,
                                  "otorgada_a": id_administrador})
        return next(s for s in self.repositorio.soporte_listar(id_vehiculo)
                    if s["id_autorizacion"] == id_autorizacion)

    def soporte_revocar(self, principal, id_vehiculo):
        self._exigir_propietario(principal, id_vehiculo)
        revocadas = self.repositorio.soporte_revocar(id_vehiculo, principal.id_usuario)
        self.auditoria.registrar(principal.actor(), "soporte.revocar", "unidad", id_vehiculo,
                                 {"revocadas": revocadas})
        return {"id_vehiculo": id_vehiculo, "revocadas": revocadas}
