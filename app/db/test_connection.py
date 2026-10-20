import os
import sys
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv


# Cargar las variables del archivo .env situado en la raíz.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def probar_conexion():
    conexion = None
    cursor = None

    try:
        conexion = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT", "3306")),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            connection_timeout=5,
        )

        print("CONEXION_MYSQL_OK")

        cursor = conexion.cursor()
        cursor.callproc("sp_obtener_vehiculos")

        for resultado in cursor.stored_results():
            vehiculos = resultado.fetchall()

            print("CONSULTA_SP_OK")
            print(f"Vehiculos encontrados: {len(vehiculos)}")

            # Solo mostramos el identificador, no datos sensibles.
            if vehiculos:
                print(f"Primer ID de vehiculo: {vehiculos[0][0]}")

    except mysql.connector.Error as error:
        print(f"ERROR_MYSQL: {error.__class__.__name__}")
        print(f"Detalle: {error.msg}")
        sys.exit(1)

    except (TypeError, ValueError):
        print("ERROR_CONFIGURACION: revisa DB_PORT y las variables de .env")
        sys.exit(1)

    finally:
        if cursor is not None:
            cursor.close()

        if conexion is not None and conexion.is_connected():
            conexion.close()
            print("CONEXION_CERRADA")


if __name__ == "__main__":
    probar_conexion()