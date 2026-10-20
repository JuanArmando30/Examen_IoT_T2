
from app.db.database import Database


def probar_database():
    db = Database()

    with db.connection() as conexion:
        print("CONEXION_POO_OK")

        cursor = conexion.cursor()

        try:
            cursor.callproc("sp_obtener_vehiculos")

            for resultado in cursor.stored_results():
                vehiculos = resultado.fetchall()

                print("STORED_PROCEDURE_OK")
                print(f"Vehiculos encontrados: {len(vehiculos)}")

                if vehiculos:
                    print(f"Primer ID: {vehiculos[0][0]}")

        finally:
            cursor.close()

    print("CONEXION_CERRADA_OK")


if __name__ == "__main__":
    probar_database()
