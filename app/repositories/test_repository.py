"""Prueba manual de lectura: python -m app.repositories.test_repository"""

from app.repositories.stored_procedure_repository import (
    StoredProcedureRepository,
)


def mostrar(titulo, datos):
    print(f"\n--- {titulo} ---")

    if isinstance(datos, list):
        print(f"{len(datos)} registro(s)")
        for fila in datos:
            print(fila)
    else:
        print(datos)


def probar_repositorio():
    repo = StoredProcedureRepository()

    mostrar("VEHICULOS", repo.obtener_vehiculos())
    mostrar("VEHICULO 1", repo.obtener_vehiculo(1))
    mostrar("COMANDOS DEL VEHICULO 1", repo.obtener_comandos_vehiculo(1))
    mostrar("ESTADO DEL VEHICULO 1", repo.obtener_estado(1))
    mostrar("HISTORIAL DEL VEHICULO 1", repo.obtener_historial(1))
    mostrar("DEMOS DEL VEHICULO 1", repo.obtener_demos(1))
    mostrar("MOVIMIENTOS DE LA DEMO 1", repo.obtener_movimientos_demo(1))

    print("\nPRUEBAS DE CONSULTA FINALIZADAS")


if __name__ == "__main__":
    probar_repositorio()
