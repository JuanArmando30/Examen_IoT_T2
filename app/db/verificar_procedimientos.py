"""Comprueba que los procedimientos almacenados existen en RDS.

Uso:  python -m app.db.verificar_procedimientos
Los 21 originales son obligatorios; los 25 de ADMINISTRACIÓN (V009) se
informan aparte (faltan mientras no se aplique esa migración).
"""

import sys

from app.db.migrar import base_administrativa
from app.repositories.stored_procedure_repository import (
    PROCEDIMIENTOS_NUEVOS,
    PROCEDIMIENTOS_ORIGINALES,
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
    nuevos = len(PROCEDIMIENTOS_NUEVOS & existentes)

    print(f"Originales: {len(PROCEDIMIENTOS_ORIGINALES & existentes)} de {len(PROCEDIMIENTOS_ORIGINALES)}")
    print(f"Administración (V009): {nuevos} de {len(PROCEDIMIENTOS_NUEVOS)}")

    if faltan:
        print("FALTAN:", ", ".join(faltan))
        sys.exit(1)

    print("OK: los 21 procedimientos originales existen."
          + ("" if nuevos == len(PROCEDIMIENTOS_NUEVOS) else " Falta aplicar V009."))


if __name__ == "__main__":
    main()
