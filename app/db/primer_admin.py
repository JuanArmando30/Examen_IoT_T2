"""Crea el PRIMER administrador (o un código para un administrador sin acceso).

Se ejecuta en el servidor, con el .env de la API (cuenta normal de la API y
TOKEN_SECRETO). No pide contraseñas: genera un código de restablecimiento de
un solo uso que se muestra UNA vez; con él se fija la contraseña en
POST /auth/restablecer (o desde la página de inicio de sesión).

    python -m app.db.primer_admin --correo admin@empresa.com --nombre "Administración"
    python -m app.db.primer_admin --correo admin@empresa.com --restablecer
"""

import argparse
import sys
from datetime import timedelta

from app.core import tokens
from app.core.config import AuthSettings
from app.core.exceptions import ErrorAplicacion
from app.repositories.stored_procedure_repository import StoredProcedureRepository
from app.services.administracion import VERSION_AUTENTICACION, UsuarioService


def _buscar(repo, correo):
    filas = repo.listar_usuarios(None, None, correo, 5, 0)
    return next((f for f in filas if f["correo"] == correo), None)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--correo", required=True)
    p.add_argument("--nombre", default="Administración")
    p.add_argument("--restablecer", action="store_true",
                   help="El administrador ya existe: solo generar un código nuevo.")
    args = p.parse_args(argv)

    auth = AuthSettings.from_env()
    if not auth.configurado:
        print("Falta TOKEN_SECRETO en .env (mínimo 32 caracteres). Genera uno con:\n"
              "  python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
        return 2

    correo = UsuarioService.normalizar_correo(args.correo)
    repo = StoredProcedureRepository()
    try:
        if repo.version_esquema() < VERSION_AUTENTICACION:
            print("La base aún no tiene la migración V010. Aplícala primero (migrar probar / aplicar).")
            return 2

        usuario = _buscar(repo, correo)
        if args.restablecer:
            if usuario is None or usuario["rol"] != "admin":
                print("No existe un administrador con ese correo.")
                return 1
            id_usuario = usuario["id_usuario"]
        else:
            admins = [u for u in repo.listar_usuarios("admin", True, None, 5, 0)]
            if admins:
                print("Ya hay administradores activos; crea los demás desde la página de "
                      "Administración. (Para recuperar acceso usa --restablecer.)")
                return 1
            if usuario is not None:
                print("Ese correo ya existe con otro rol; usa otro correo.")
                return 1
            id_usuario = repo.crear_usuario(correo, args.nombre.strip()[:100], "admin")
            repo.registrar_auditoria(None, "sistema", "usuario.crear", "usuario", str(id_usuario),
                                     "ok", '{"origen": "primer_admin"}', None)

        codigo = tokens.codigo_restablecimiento()
        expira = tokens.ahora() + timedelta(minutes=auth.codigo_min)
        repo.codigo_crear(id_usuario, tokens.huella(auth, tokens.normalizar_codigo(codigo)),
                          None, expira.replace(tzinfo=None))
        repo.registrar_auditoria(None, "sistema", "usuario.codigo_restablecimiento", "usuario",
                                 str(id_usuario), "ok", '{"origen": "primer_admin"}', None)
    except ErrorAplicacion as error:
        print(f"Error: {error.mensaje}")
        return 1

    print(f"Administrador: {correo} (id {id_usuario})")
    print(f"Código de un solo uso (vence en {auth.codigo_min} min, se muestra solo esta vez):")
    print(f"\n    {codigo}\n")
    print("Úsalo en POST /auth/restablecer con tu correo y una contraseña nueva "
          "(10+ caracteres, letras y números).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
