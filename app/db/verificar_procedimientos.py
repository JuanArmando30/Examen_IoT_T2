"""Comprueba que los procedimientos almacenados existen en RDS.

Uso:  python -m app.db.verificar_procedimientos
Los 21 originales son obligatorios; los de ADMINISTRACIÓN (V009, 25) y de
AUTENTICACIÓN (V010, 14 nuevos) se informan aparte (faltan mientras no se
apliquen esas migraciones).
"""

import sys

from app.db.migrar import base_administrativa
from app.repositories.stored_procedure_repository import (
    PROCEDIMIENTOS_ORIGINALES,
    PROCEDIMIENTOS_V009_ESCRITURA,
    PROCEDIMIENTOS_V009_LECTURA,
    PROCEDIMIENTOS_V010,
)

GRUPOS = (
    ("Administración (V009)", PROCEDIMIENTOS_V009_LECTURA | PROCEDIMIENTOS_V009_ESCRITURA),
    ("Autenticación (V010)", PROCEDIMIENTOS_V010),
)


def main():
    db = base_administrativa()

    with db.connection() as conexion:
        cursor = conexion.cursor()

        try:
            cursor.execute(
                "SELECT ROUTINE_NAME FROM information_schema.ROUTINES "
                "WHERE ROUTINE_SCHEMA = %s AND ROUTINE_TYPE = 'PROCEDURE'",
                (db.config.db_name,),
            )
            existentes = {fila[0] for fila in cursor.fetchall()}
        finally:
            cursor.close()

    faltan = sorted(PROCEDIMIENTOS_ORIGINALES - existentes)
    print(f"Originales: {len(PROCEDIMIENTOS_ORIGINALES & existentes)} de {len(PROCEDIMIENTOS_ORIGINALES)}")
    pendientes = []
    for nombre, grupo in GRUPOS:
        n = len(grupo & existentes)
        print(f"{nombre}: {n} de {len(grupo)}")
        if n < len(grupo):
            pendientes.append(nombre)

    if faltan:
        print("FALTAN:", ", ".join(faltan))
        sys.exit(1)

    print("OK: los 21 procedimientos originales existen."
          + (f" Pendiente: {', '.join(pendientes)}." if pendientes else ""))


if __name__ == "__main__":
    main()
