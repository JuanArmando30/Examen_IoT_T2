"""Comprueba que los 21 SP existen en RDS.

Uso:  python -m app.db.verificar_procedimientos
"""

import sys

from app.db.database import Database
from app.repositories.stored_procedure_repository import (
    PROCEDIMIENTOS_PERMITIDOS,
)


def main():
    db = Database()

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

    faltantes = sorted(PROCEDIMIENTOS_PERMITIDOS - existentes)

    print(f"Procedimientos esperados: {len(PROCEDIMIENTOS_PERMITIDOS)}")
    print(f"Encontrados: {len(PROCEDIMIENTOS_PERMITIDOS & existentes)}")

    if faltantes:
        print("FALTAN:", ", ".join(faltantes))
        sys.exit(1)

    print("OK: los 21 procedimientos almacenados existen.")


if __name__ == "__main__":
    main()
