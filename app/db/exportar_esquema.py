"""Exporta la ESTRUCTURA de la base de datos de RDS a un archivo Markdown.

Etapa 1 (diagnóstico) del proyecto ADMINISTRACIÓN. Es de SOLO LECTURA:
  - Abre una transacción READ ONLY y solo ejecuta SELECT / SHOW.
  - NO exporta filas: de cada tabla solo se cuenta cuántos registros tiene.
  - NO escribe nada en la base de datos ni imprime host ni contraseña.
  - Sí incluye los nombres de las cuentas de MySQL (DEFINER de los
    procedimientos y los privilegios de la cuenta de la API), que sirven
    para planear privilegios mínimos.

Uso (en el servidor, dentro de C:\\vehiculo_oit):
    .\\.venv\\Scripts\\python.exe -m app.db.exportar_esquema

Genera diagnostico\\esquema_rds_<fecha>.md (la carpeta está en .gitignore).
"""

import sys
from datetime import datetime

import mysql.connector

from app.core.config import PROJECT_ROOT
from app.db.migrar import base_administrativa
from app.repositories.stored_procedure_repository import (
    PROCEDIMIENTOS_PERMITIDOS,
)

CARPETA_SALIDA = PROJECT_ROOT / "diagnostico"


def _id(nombre):
    """Identificador MySQL entre comillas invertidas (nombres de information_schema)."""
    return "`" + str(nombre).replace("`", "``") + "`"


class Exportador:
    def __init__(self, conexion, base):
        self.conexion = conexion
        self.base = base
        self.lineas = []
        self.avisos = []

    # ------------------------- utilidades -------------------------

    def consultar(self, sql, parametros=()):
        cursor = self.conexion.cursor()
        try:
            cursor.execute(sql, parametros)
            columnas = [c[0] for c in cursor.description] if cursor.description else []
            return columnas, cursor.fetchall()
        finally:
            cursor.close()

    def intentar(self, descripcion, sql, parametros=()):
        """Como consultar(), pero un error de privilegios no detiene el informe."""
        try:
            return self.consultar(sql, parametros)
        except mysql.connector.Error as error:
            self.avisos.append(f"{descripcion}: sin acceso ({error.errno}: {error.msg})")
            return [], []

    def escribir(self, texto=""):
        self.lineas.append(texto)

    def tabla_md(self, columnas, filas):
        if not filas:
            self.escribir("_(sin registros)_")
            self.escribir()
            return
        self.escribir("| " + " | ".join(columnas) + " |")
        self.escribir("|" + "---|" * len(columnas))
        for fila in filas:
            celdas = ["" if v is None else str(v).replace("|", "\\|").replace("\n", " ") for v in fila]
            self.escribir("| " + " | ".join(celdas) + " |")
        self.escribir()

    def bloque_sql(self, texto):
        self.escribir("```sql")
        self.escribir(str(texto).strip())
        self.escribir("```")
        self.escribir()

    # ------------------------- secciones -------------------------

    def servidor(self):
        self.escribir("## 1. Servidor y configuración")
        self.escribir()
        _, filas = self.consultar(
            "SELECT VERSION(), CURRENT_USER(), DATABASE(), @@global.time_zone, "
            "@@session.time_zone, @@system_time_zone, NOW(), UTC_TIMESTAMP(), "
            "@@character_set_database, @@collation_database, @@sql_mode, "
            "@@default_storage_engine, @@transaction_isolation"
        )
        nombres = ["Versión de MySQL", "Cuenta usada por la API", "Base de datos",
                   "time_zone global", "time_zone de la sesión", "Zona del sistema",
                   "NOW()", "UTC_TIMESTAMP()", "Juego de caracteres", "Intercalación",
                   "sql_mode", "Motor por defecto", "Aislamiento de transacciones"]
        self.tabla_md(["Dato", "Valor"], list(zip(nombres, filas[0])))

        self.escribir("### Privilegios de la cuenta de la API")
        self.escribir()
        _, grants = self.intentar("SHOW GRANTS", "SHOW GRANTS FOR CURRENT_USER()")
        for (g,) in grants:
            self.escribir(f"- `{g}`")
        if not grants:
            self.escribir("_No disponible (ver Avisos)._")
        self.escribir()

    def tablas(self):
        self.escribir("## 2. Tablas y vistas")
        self.escribir()
        _, filas = self.consultar(
            "SELECT TABLE_NAME, TABLE_TYPE, ENGINE, TABLE_COLLATION, CREATE_TIME, TABLE_COMMENT "
            "FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s ORDER BY TABLE_TYPE, TABLE_NAME",
            (self.base,),
        )
        resumen = []
        base_tablas = []
        for nombre, tipo, motor, intercalacion, creada, comentario in filas:
            registros = "—"
            if tipo == "BASE TABLE":
                base_tablas.append(nombre)
                _, conteo = self.intentar(f"COUNT de {nombre}", f"SELECT COUNT(*) FROM {_id(nombre)}")
                registros = conteo[0][0] if conteo else "sin acceso"
            resumen.append((nombre, tipo, motor, intercalacion, registros, creada, comentario))
        self.tabla_md(["Tabla", "Tipo", "Motor", "Intercalación", "Registros (conteo)", "Creada", "Comentario"], resumen)

        for nombre in base_tablas:
            self.escribir(f"### Tabla `{nombre}`")
            self.escribir()
            _, ddl = self.intentar(f"SHOW CREATE TABLE {nombre}", f"SHOW CREATE TABLE {_id(nombre)}")
            if ddl:
                self.bloque_sql(ddl[0][1])

        vistas = [f[0] for f in filas if f[1] == "VIEW"]
        for nombre in vistas:
            self.escribir(f"### Vista `{nombre}`")
            self.escribir()
            _, ddl = self.intentar(f"SHOW CREATE VIEW {nombre}", f"SHOW CREATE VIEW {_id(nombre)}")
            if ddl:
                self.bloque_sql(ddl[0][1])

    def relaciones(self):
        self.escribir("## 3. Llaves foráneas")
        self.escribir()
        columnas, filas = self.consultar(
            "SELECT k.TABLE_NAME AS tabla, k.COLUMN_NAME AS columna, k.REFERENCED_TABLE_NAME AS referencia, "
            "k.REFERENCED_COLUMN_NAME AS columna_ref, k.CONSTRAINT_NAME AS restriccion, "
            "r.UPDATE_RULE AS al_actualizar, r.DELETE_RULE AS al_eliminar "
            "FROM information_schema.KEY_COLUMN_USAGE k "
            "JOIN information_schema.REFERENTIAL_CONSTRAINTS r "
            "  ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME "
            "WHERE k.TABLE_SCHEMA = %s AND k.REFERENCED_TABLE_NAME IS NOT NULL "
            "ORDER BY k.TABLE_NAME, k.CONSTRAINT_NAME, k.ORDINAL_POSITION",
            (self.base,),
        )
        self.tabla_md(columnas, filas)

        self.escribir("### Índices (resumen)")
        self.escribir()
        columnas, filas = self.consultar(
            "SELECT TABLE_NAME AS tabla, INDEX_NAME AS indice, "
            "GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS columnas, "
            "IF(MIN(NON_UNIQUE) = 0, 'UNIQUE', '') AS unico "
            "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = %s "
            "GROUP BY TABLE_NAME, INDEX_NAME ORDER BY TABLE_NAME, INDEX_NAME",
            (self.base,),
        )
        self.tabla_md(columnas, filas)

    def rutinas(self):
        self.escribir("## 4. Procedimientos y funciones")
        self.escribir()
        _, filas = self.consultar(
            "SELECT ROUTINE_NAME, ROUTINE_TYPE, DEFINER, SECURITY_TYPE, SQL_DATA_ACCESS, CREATED, LAST_ALTERED "
            "FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = %s ORDER BY ROUTINE_TYPE, ROUTINE_NAME",
            (self.base,),
        )
        existentes = {f[0] for f in filas if f[1] == "PROCEDURE"}
        faltan = sorted(PROCEDIMIENTOS_PERMITIDOS - existentes)
        extra = sorted(existentes - PROCEDIMIENTOS_PERMITIDOS)
        self.escribir(f"- Esperados por la API: **{len(PROCEDIMIENTOS_PERMITIDOS)}** · encontrados: "
                      f"**{len(PROCEDIMIENTOS_PERMITIDOS & existentes)}**")
        self.escribir(f"- Faltan: {', '.join(faltan) if faltan else 'ninguno'}")
        self.escribir(f"- Existen pero la API no los usa: {', '.join(extra) if extra else 'ninguno'}")
        self.escribir()
        self.tabla_md(["Nombre", "Tipo", "Definer", "Seguridad", "Acceso a datos", "Creado", "Modificado"], filas)

        _, parametros = self.consultar(
            "SELECT SPECIFIC_NAME, ORDINAL_POSITION, PARAMETER_MODE, PARAMETER_NAME, DTD_IDENTIFIER "
            "FROM information_schema.PARAMETERS WHERE SPECIFIC_SCHEMA = %s AND ORDINAL_POSITION > 0 "
            "ORDER BY SPECIFIC_NAME, ORDINAL_POSITION",
            (self.base,),
        )
        firma = {}
        for rutina, _pos, modo, nombre, tipo in parametros:
            firma.setdefault(rutina, []).append(f"{modo or ''} {nombre} {tipo}".strip())

        for nombre, tipo, *_ in filas:
            self.escribir(f"### {tipo.title()} `{nombre}`({', '.join(firma.get(nombre, []))})")
            self.escribir()
            orden = "SHOW CREATE PROCEDURE" if tipo == "PROCEDURE" else "SHOW CREATE FUNCTION"
            _, ddl = self.intentar(f"{orden} {nombre}", f"{orden} {_id(nombre)}")
            cuerpo = ddl[0][2] if ddl and len(ddl[0]) > 2 else None
            if cuerpo:
                self.bloque_sql(cuerpo)
            else:
                self.escribir("_Cuerpo no visible: la cuenta necesita el privilegio SHOW_ROUTINE "
                              "(o ser el DEFINER). Ejecuta este script con la cuenta administradora "
                              "de RDS si hace falta._")
                self.escribir()

    def otros(self):
        self.escribir("## 5. Disparadores y eventos programados")
        self.escribir()
        self.escribir("### Disparadores (triggers)")
        self.escribir()
        columnas, filas = self.intentar(
            "TRIGGERS",
            "SELECT TRIGGER_NAME AS disparador, EVENT_OBJECT_TABLE AS tabla, ACTION_TIMING AS momento, "
            "EVENT_MANIPULATION AS evento FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = %s",
            (self.base,),
        )
        self.tabla_md(columnas or ["disparador"], filas)
        self.escribir("### Eventos programados")
        self.escribir()
        columnas, filas = self.intentar(
            "EVENTS",
            "SELECT EVENT_NAME AS evento, STATUS AS estado, EVENT_TYPE AS tipo, INTERVAL_VALUE, INTERVAL_FIELD "
            "FROM information_schema.EVENTS WHERE EVENT_SCHEMA = %s",
            (self.base,),
        )
        self.tabla_md(columnas or ["evento"], filas)

    # ------------------------- informe -------------------------

    def generar(self):
        self.escribir(f"# Estructura de RDS · base `{self.base}`")
        self.escribir()
        self.escribir(f"Generado: {datetime.now().isoformat(timespec='seconds')} (hora del servidor EC2).")
        self.escribir("Solo estructura: sin filas de datos, sin host y sin contraseñas.")
        self.escribir()
        self.servidor()
        self.tablas()
        self.relaciones()
        self.rutinas()
        self.otros()
        if self.avisos:
            self.escribir("## Avisos")
            self.escribir()
            for aviso in self.avisos:
                self.escribir(f"- {aviso}")
            self.escribir()
        return "\n".join(self.lineas) + "\n"


def main():
    db = base_administrativa()        # DB_MIGRA_USER si existe: la cuenta de la API no puede leer la estructura
    with db.connection() as conexion:
        cursor = conexion.cursor()
        cursor.execute("START TRANSACTION READ ONLY")      # garantía: nada puede modificarse
        cursor.close()
        try:
            informe = Exportador(conexion, db.config.db_name).generar()
        finally:
            conexion.rollback()

    CARPETA_SALIDA.mkdir(exist_ok=True)
    destino = CARPETA_SALIDA / f"esquema_rds_{datetime.now():%Y%m%d_%H%M%S}.md"
    destino.write_text(informe, encoding="utf-8")
    print(f"OK: estructura exportada en {destino}")
    print("Ábrelo con:  notepad " + str(destino))


if __name__ == "__main__":
    try:
        main()
    except mysql.connector.Error as error:
        print(f"No se pudo leer la base de datos ({error.errno}): {error.msg}", file=sys.stderr)
        sys.exit(1)
