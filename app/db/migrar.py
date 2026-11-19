"""Migraciones versionadas de RDS (proyecto ADMINISTRACIÓN · Etapa 2).

Comandos (en el servidor, dentro de C:\\vehiculo_oit):

  python -m app.db.migrar plan
      Lee y valida los archivos de db/migraciones (no se conecta a RDS).
  python -m app.db.migrar probar [--conservar-copia]
      Prueba COMPLETA sobre una copia: crea <base>_prueba con la estructura,
      los datos y los 21 SP de la base real; aplica todas las migraciones,
      prueba los SP existentes, revierte todo, comprueba que la estructura
      original quedó idéntica, vuelve a aplicar y borra la copia.
      La base real solo se LEE. Si todo pasa, deja un sello con las sumas
      de verificación de los archivos probados.
  python -m app.db.migrar estado
      Migraciones aplicadas y pendientes en la base real.
  python -m app.db.migrar aplicar --respaldo <id-del-snapshot> [--hasta V00X]
      Aplica las pendientes en la base REAL. Exige el identificador del
      respaldo (queda registrado) y que `probar` haya pasado con estos
      mismos archivos.
  python -m app.db.migrar revertir V00X [--base <base>] [--confirmo-produccion --respaldo <id>]
      Revierte desde la versión indicada (de la más nueva a V00X).
  python -m app.db.migrar limpiar-copia
      Borra la copia de prueba si quedó de una prueba fallida.

Cada sentencia DDL de MySQL hace COMMIT implícito: una migración que falla
a la mitad NO se deshace sola. Por eso: respaldo previo, copia de prueba y
archivos de reversión que solo actúan sobre lo que existe (directivas @si).
"""

import argparse
import dataclasses
import hashlib
import json
import os
import re
import secrets
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import mysql.connector

from app.core.config import PROJECT_ROOT
from app.db.database import Database
from app.db.pruebas_procedimientos import PRUEBAS
from app.repositories.stored_procedure_repository import PROCEDIMIENTOS_ORIGINALES

CARPETA_MIGRACIONES = PROJECT_ROOT / "db" / "migraciones"
CARPETA_DIAGNOSTICO = PROJECT_ROOT / "diagnostico"
SELLO_PRUEBA = CARPETA_DIAGNOSTICO / "prueba_migraciones_ok.json"
TABLA_HISTORIAL = "migraciones_aplicadas"
MARCA_COPIA = "_copia_de_prueba"
SUFIJO_COPIA = "_prueba"
# Tablas que existían antes de este proyecto: ninguna migración puede cambiar su número de filas.
ORIGINALES = ("vehiculos", "comandos", "demos", "demo_movimientos", "estado_vehiculo", "historial_comandos")
# Modo SQL por defecto de MySQL 8 (estricto). RDS usa NO_ENGINE_SUBSTITUTION, que trunca en silencio.
SQL_MODE_ESTRICTO = ("ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,"
                     "ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION")
PATRON_ARCHIVO = re.compile(r"^(V\d{3})__([a-z0-9_]+)\.sql$")
TIPOS = ("tabla", "columna", "indice", "fk", "check")


class ErrorMigracion(Exception):
    """Falla controlada: se informa y el proceso se detiene."""


def _id(nombre):
    return "`" + str(nombre).replace("`", "``") + "`"


# ============================ Archivos SQL ============================

@dataclass
class Condicion:
    negada: bool
    tipo: str
    objeto: str

    def texto(self):
        return f"{'no-existe' if self.negada else 'existe'} {self.tipo} {self.objeto}"


@dataclass
class Sentencia:
    sql: str
    linea: int
    condiciones: list = field(default_factory=list)


@dataclass
class Script:
    ruta: Path
    sentencias: list
    previos: list
    verificaciones: list


@dataclass
class Migracion:
    version: str
    nombre: str
    checksum: str
    up: Script
    down: Script

    @property
    def descripcion(self):
        return self.nombre.replace("_", " ")


def _condicion(texto, ruta, n):
    partes = texto.split()
    if len(partes) != 3 or partes[0] not in ("existe", "no-existe") or partes[1] not in TIPOS:
        raise ErrorMigracion(
            f"{ruta.name}:{n}: condición inválida «{texto}». "
            f"Formato: existe|no-existe {'|'.join(TIPOS)} objeto")
    if partes[1] != "tabla" and "." not in partes[2]:
        raise ErrorMigracion(f"{ruta.name}:{n}: usa tabla.nombre en «{texto}»")
    return Condicion(partes[0] == "no-existe", partes[1], partes[2])


def analizar(ruta):
    """Divide un archivo en sentencias (por «;» fuera de comillas y comentarios) y lee sus directivas."""
    lineas = ruta.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    sentencias, previos, verificaciones, pendientes = [], [], [], []
    actual, linea_inicio = [], None
    comilla, bloque = None, False
    delimitador = ";"                    # se cambia con «DELIMITER $$» (para crear procedimientos), como en el cliente mysql

    for n, linea in enumerate(lineas, 1):
        limpia = linea.strip()
        if limpia.upper().startswith("DELIMITER ") and not actual and not comilla and not bloque:
            delimitador = limpia.split(None, 1)[1].strip()
            if not delimitador or "'" in delimitador or '"' in delimitador:
                raise ErrorMigracion(f"{ruta.name}:{n}: DELIMITER inválido")
            continue
        if limpia.startswith("-- @"):
            if actual or comilla or bloque:
                raise ErrorMigracion(f"{ruta.name}:{n}: directiva dentro de una sentencia")
            clave, _, resto = limpia[4:].partition(" ")
            resto = resto.strip()
            if clave == "previo":
                previos.append(_condicion(resto, ruta, n))
            elif clave == "si":
                pendientes.append(_condicion(resto, ruta, n))
            elif clave == "verificar":
                if not resto.upper().startswith("SELECT"):
                    raise ErrorMigracion(f"{ruta.name}:{n}: @verificar debe ser un SELECT")
                verificaciones.append((n, resto))
            else:
                raise ErrorMigracion(f"{ruta.name}:{n}: directiva desconocida @{clave}")
            continue

        trozo, i = [], 0
        while i < len(linea):
            c = linea[i]
            if bloque:
                if linea.startswith("*/", i):
                    bloque = False
                    i += 2
                else:
                    i += 1
                continue
            if comilla:
                trozo.append(c)
                if c == "\\" and comilla != "`" and i + 1 < len(linea):
                    trozo.append(linea[i + 1])
                    i += 2
                    continue
                if c == comilla:
                    if i + 1 < len(linea) and linea[i + 1] == comilla:
                        trozo.append(c)
                        i += 2
                        continue
                    comilla = None
                i += 1
                continue
            if linea.startswith("-- ", i) or linea[i:].rstrip() == "--" or c == "#":
                break                                   # comentario hasta el final de la línea
            if linea.startswith("/*", i):
                bloque = True
                i += 2
                continue
            if c in ("'", '"', "`"):
                comilla = c
                trozo.append(c)
                i += 1
                continue
            if linea.startswith(delimitador, i):
                actual.append("".join(trozo))
                trozo = []
                sql = "\n".join(actual).strip()
                if sql:
                    sentencias.append(Sentencia(sql, linea_inicio or n, pendientes))
                elif pendientes:
                    raise ErrorMigracion(f"{ruta.name}:{n}: condición @si sin sentencia")
                pendientes, actual, linea_inicio = [], [], None
                i += len(delimitador)
                continue
            trozo.append(c)
            i += 1

        resto_linea = "".join(trozo)
        if resto_linea.strip():
            if linea_inicio is None:
                linea_inicio = n
            actual.append(resto_linea)
        elif actual:
            actual.append("")

    if "\n".join(actual).strip():
        raise ErrorMigracion(f"{ruta.name}: la última sentencia no termina en «{delimitador}»")
    if delimitador != ";":
        raise ErrorMigracion(f"{ruta.name}: falta «DELIMITER ;» al final")
    if comilla or bloque:
        raise ErrorMigracion(f"{ruta.name}: comilla o comentario sin cerrar")
    if pendientes:
        raise ErrorMigracion(f"{ruta.name}: condición @si al final sin sentencia")
    return Script(ruta, sentencias, previos, verificaciones)


def cargar_migraciones():
    if not CARPETA_MIGRACIONES.is_dir():
        raise ErrorMigracion(f"No existe {CARPETA_MIGRACIONES}")
    migraciones = []
    for ruta in sorted(CARPETA_MIGRACIONES.glob("V*.sql")):
        if ruta.name.endswith(".down.sql"):
            continue
        m = PATRON_ARCHIVO.match(ruta.name)
        if not m:
            raise ErrorMigracion(f"Nombre inválido: {ruta.name} (usa V001__descripcion.sql)")
        down = ruta.with_name(ruta.name[:-4] + ".down.sql")
        if not down.exists():
            raise ErrorMigracion(f"Falta la reversión {down.name}")
        texto = ruta.read_text(encoding="utf-8").replace("\r\n", "\n")
        migraciones.append(Migracion(
            version=m.group(1), nombre=m.group(2),
            checksum=hashlib.sha256(texto.encode("utf-8")).hexdigest(),
            up=analizar(ruta), down=analizar(down),
        ))
    versiones = [m.version for m in migraciones]
    esperadas = [f"V{i:03d}" for i in range(1, len(versiones) + 1)]
    if versiones != esperadas:
        raise ErrorMigracion(f"Versiones no consecutivas: {versiones}")
    return migraciones


# ============================ Base de datos ============================

class Ejecutor:
    def __init__(self, conexion, base_real):
        self.con = conexion
        self.base_real = base_real
        self.lineas = []

    # ---------------- utilidades ----------------

    def log(self, texto=""):
        print(texto, flush=True)
        self.lineas.append(texto)

    def ejecutar(self, sql, parametros=None):
        cursor = self.con.cursor()
        try:
            if parametros is None:
                cursor.execute(sql)            # sin parámetros: los «%» del SQL no se interpretan
            else:
                cursor.execute(sql, parametros)
            return cursor.fetchall() if cursor.with_rows else []
        finally:
            cursor.close()

    def valor(self, sql, parametros=None):
        filas = self.ejecutar(sql, parametros)
        return filas[0][0] if filas else None

    def llamar(self, nombre, argumentos=()):
        cursor = self.con.cursor()
        try:
            cursor.callproc(nombre, tuple(argumentos))
            filas = []
            for resultado in cursor.stored_results():
                if resultado.description:
                    columnas = [c[0] for c in resultado.description]
                    filas.extend(dict(zip(columnas, f)) for f in resultado.fetchall())
            return filas
        finally:
            cursor.close()

    def preparar_sesion(self):
        self.con.autocommit = True
        for sql in (f"SET SESSION sql_mode = '{SQL_MODE_ESTRICTO}'",
                    "SET SESSION time_zone = '+00:00'",
                    "SET SESSION foreign_key_checks = 1",
                    "SET SESSION lock_wait_timeout = 15"):
            self.ejecutar(sql)

    def usar(self, base):
        self.ejecutar(f"USE {_id(base)}")

    def existe(self, base, condicion):
        tipo, objeto = condicion.tipo, condicion.objeto
        if tipo == "tabla":
            sql = "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s"
            parametros = (base, objeto)
        else:
            tabla, nombre = objeto.split(".", 1)
            if tipo == "columna":
                sql = ("SELECT COUNT(*) FROM information_schema.COLUMNS "
                       "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s")
            elif tipo == "indice":
                sql = ("SELECT COUNT(*) FROM information_schema.STATISTICS "
                       "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME=%s")
            else:
                restriccion = "FOREIGN KEY" if tipo == "fk" else "CHECK"
                sql = ("SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS "
                       "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND CONSTRAINT_NAME=%s "
                       f"AND CONSTRAINT_TYPE='{restriccion}'")
            parametros = (base, tabla, nombre)
        return (self.valor(sql, parametros) or 0) > 0

    def cumple(self, base, condiciones):
        return all(self.existe(base, c) != c.negada for c in condiciones)

    def tablas(self, base):
        return {f[0] for f in self.ejecutar(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE'",
            (base,))}

    def procedimientos(self, base):
        return {f[0] for f in self.ejecutar(
            "SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=%s AND ROUTINE_TYPE='PROCEDURE'",
            (base,))}

    def conteos(self, base):
        existentes = self.tablas(base)
        return {t: self.valor(f"SELECT COUNT(*) FROM {_id(base)}.{_id(t)}") for t in ORIGINALES if t in existentes}

    def estructura(self, base, tablas):
        """Columnas, índices, llaves y CHECK de cada tabla (sin AUTO_INCREMENT ni el orden de los índices)."""
        resultado = {}
        for t in tablas:
            columnas = self.ejecutar(
                "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COALESCE(COLUMN_DEFAULT, '∅'), EXTRA, "
                "COALESCE(GENERATION_EXPRESSION, ''), COALESCE(CHARACTER_SET_NAME, ''), COALESCE(COLLATION_NAME, '') "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION",
                (base, t))
            indices = self.ejecutar(
                "SELECT INDEX_NAME, NON_UNIQUE, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) "
                "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
                "GROUP BY INDEX_NAME, NON_UNIQUE ORDER BY INDEX_NAME",
                (base, t))
            llaves = self.ejecutar(
                "SELECT k.CONSTRAINT_NAME, GROUP_CONCAT(k.COLUMN_NAME ORDER BY k.ORDINAL_POSITION), "
                "k.REFERENCED_TABLE_NAME, GROUP_CONCAT(k.REFERENCED_COLUMN_NAME ORDER BY k.ORDINAL_POSITION), "
                "r.UPDATE_RULE, r.DELETE_RULE "
                "FROM information_schema.KEY_COLUMN_USAGE k "
                "JOIN information_schema.REFERENTIAL_CONSTRAINTS r "
                "  ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME "
                "WHERE k.TABLE_SCHEMA=%s AND k.TABLE_NAME=%s AND k.REFERENCED_TABLE_NAME IS NOT NULL "
                "GROUP BY k.CONSTRAINT_NAME, k.REFERENCED_TABLE_NAME, r.UPDATE_RULE, r.DELETE_RULE "
                "ORDER BY k.CONSTRAINT_NAME",
                (base, t))
            checks = self.ejecutar(
                "SELECT cc.CONSTRAINT_NAME, cc.CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS cc "
                "JOIN information_schema.TABLE_CONSTRAINTS tc "
                "  ON tc.CONSTRAINT_SCHEMA = cc.CONSTRAINT_SCHEMA AND tc.CONSTRAINT_NAME = cc.CONSTRAINT_NAME "
                "WHERE cc.CONSTRAINT_SCHEMA=%s AND tc.TABLE_NAME=%s AND tc.CONSTRAINT_TYPE='CHECK' ORDER BY 1",
                (base, t))
            resultado[t] = {
                "columnas": [tuple(str(v) for v in f) for f in columnas],
                "indices": sorted(tuple(str(v) for v in f) for f in indices),
                "llaves": sorted(tuple(str(v) for v in f) for f in llaves),
                "checks": sorted(tuple(str(v) for v in f) for f in checks),
            }
        return resultado

    # ---------------- historial de migraciones ----------------

    def asegurar_historial(self, base):
        self.ejecutar(
            f"CREATE TABLE IF NOT EXISTS {_id(base)}.{TABLA_HISTORIAL} ("
            "  version      VARCHAR(10)  NOT NULL,"
            "  descripcion  VARCHAR(150) NOT NULL,"
            "  checksum     CHAR(64)     NOT NULL,"
            "  aplicado_en  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "  aplicado_por VARCHAR(100) NOT NULL,"
            "  respaldo     VARCHAR(120) DEFAULT NULL,"
            "  duracion_ms  INT UNSIGNED NOT NULL DEFAULT 0,"
            "  PRIMARY KEY (version)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci")

    def aplicadas(self, base):
        if TABLA_HISTORIAL not in self.tablas(base):
            return {}
        return {f[0]: f[1] for f in self.ejecutar(
            f"SELECT version, checksum FROM {_id(base)}.{TABLA_HISTORIAL} ORDER BY version")}

    # ---------------- aplicar / revertir ----------------

    def _proteger(self, base, produccion):
        if base == self.base_real and not produccion:
            raise ErrorMigracion("Protección: esta operación no puede tocar la base real.")
        if base != self.base_real and not base.endswith(SUFIJO_COPIA):
            raise ErrorMigracion(f"Protección: «{base}» no es la base real ni una copia de prueba.")

    def aplicar_up(self, base, mig, respaldo, produccion=False):
        self._proteger(base, produccion)
        self.usar(base)
        for c in mig.up.previos:
            if self.existe(base, c) == c.negada:
                raise ErrorMigracion(f"{mig.version}: comprobación previa no se cumple: {c.texto()}. No se ejecutó nada.")
        antes = self.conteos(base)
        inicio = time.monotonic()
        for i, s in enumerate(mig.up.sentencias, 1):
            if not self.cumple(base, s.condiciones):
                self.log(f"      · sentencia {i} omitida ({'; '.join(c.texto() for c in s.condiciones)})")
                continue
            try:
                self.ejecutar(s.sql)
            except mysql.connector.Error as error:
                raise ErrorMigracion(
                    f"{mig.version}: falló la sentencia {i} (línea {s.linea}): {error.errno} {error.msg}. "
                    f"Lo ya ejecutado NO se deshace solo: revierte {mig.version} antes de reintentar.") from error
        for linea, consulta in mig.up.verificaciones:
            if self.valor(consulta) != 1:
                raise ErrorMigracion(f"{mig.version}: no se cumplió la verificación de la línea {linea}: {consulta}")
        despues = self.conteos(base)
        if antes != despues:
            raise ErrorMigracion(f"{mig.version}: cambió el número de registros de tablas existentes: {antes} → {despues}")
        duracion = int((time.monotonic() - inicio) * 1000)
        self.asegurar_historial(base)
        self.ejecutar(
            f"INSERT INTO {_id(base)}.{TABLA_HISTORIAL} (version, descripcion, checksum, aplicado_por, respaldo, duracion_ms) "
            "VALUES (%s, %s, %s, CURRENT_USER(), %s, %s)",
            (mig.version, mig.descripcion, mig.checksum, respaldo, duracion))
        self.log(f"   ✓ {mig.version} {mig.descripcion} · {len(mig.up.sentencias)} sentencias · {duracion} ms · registros iguales")

    def aplicar_down(self, base, mig, produccion=False):
        self._proteger(base, produccion)
        self.usar(base)
        antes = self.conteos(base)
        for i, s in enumerate(mig.down.sentencias, 1):
            if not self.cumple(base, s.condiciones):
                continue
            try:
                self.ejecutar(s.sql)
            except mysql.connector.Error as error:
                raise ErrorMigracion(
                    f"{mig.version} (reversión): falló la sentencia {i} (línea {s.linea}): {error.errno} {error.msg}") from error
        for linea, consulta in mig.down.verificaciones:
            if self.valor(consulta) != 1:
                raise ErrorMigracion(f"{mig.version} (reversión): no se cumplió la verificación de la línea {linea}")
        despues = self.conteos(base)
        if antes != despues:
            raise ErrorMigracion(f"{mig.version} (reversión): cambió el número de registros: {antes} → {despues}")
        if TABLA_HISTORIAL in self.tablas(base):
            self.ejecutar(f"DELETE FROM {_id(base)}.{TABLA_HISTORIAL} WHERE version = %s", (mig.version,))
        self.log(f"   ✓ {mig.version} revertida")

    # ---------------- copia de prueba ----------------

    def borrar_copia(self, copia):
        if copia == self.base_real or not copia.endswith(SUFIJO_COPIA):
            raise ErrorMigracion("Protección: solo se borra la copia de prueba.")
        if MARCA_COPIA not in self.tablas(copia):
            raise ErrorMigracion(f"Protección: «{copia}» no tiene la marca {MARCA_COPIA}; no se borra.")
        self.ejecutar(f"DROP DATABASE {_id(copia)}")

    def crear_copia(self, origen, copia):
        existe = self.valor("SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s", (copia,))
        if existe:
            self.borrar_copia(copia)                       # solo si es nuestra (marca); si no, se detiene
            self.log(f"   · copia anterior «{copia}» borrada")
        self.ejecutar(f"CREATE DATABASE {_id(copia)} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
        self.usar(copia)
        self.ejecutar(f"CREATE TABLE {MARCA_COPIA} (origen VARCHAR(64) NOT NULL, "
                      "creada_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        self.ejecutar(f"INSERT INTO {MARCA_COPIA} (origen) VALUES (%s)", (origen,))
        self.ejecutar("SET SESSION foreign_key_checks = 0")
        try:
            for tabla in sorted(self.tablas(origen)):
                ddl = self.ejecutar(f"SHOW CREATE TABLE {_id(origen)}.{_id(tabla)}")[0][1]
                self.ejecutar(ddl)                         # se crea en la copia (USE copia)
                # Las columnas generadas (p. ej. asignaciones.vehiculo_vigente) no se copian: MySQL las calcula.
                columnas = ", ".join(_id(f[0]) for f in self.ejecutar(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
                    "AND EXTRA NOT IN ('VIRTUAL GENERATED', 'STORED GENERATED') ORDER BY ORDINAL_POSITION",
                    (origen, tabla)))
                self.ejecutar(f"INSERT INTO {_id(copia)}.{_id(tabla)} ({columnas}) "
                              f"SELECT {columnas} FROM {_id(origen)}.{_id(tabla)}")
        finally:
            self.ejecutar("SET SESSION foreign_key_checks = 1")
        for nombre in sorted(self.procedimientos(origen)):
            fila = self.ejecutar(f"SHOW CREATE PROCEDURE {_id(origen)}.{_id(nombre)}")[0]
            if not fila[2]:
                raise ErrorMigracion(f"No se puede leer el cuerpo de {nombre} (falta el privilegio SHOW_ROUTINE).")
            self.ejecutar("SET SESSION sql_mode = %s", (fila[1],))   # mismo modo con el que se creó en la base real
            self.ejecutar(fila[2])
        self.ejecutar(f"SET SESSION sql_mode = '{SQL_MODE_ESTRICTO}'")

    # ---------------- pruebas de compatibilidad ----------------

    def probar_lecturas(self, base):
        """Los SP de consulta responden (se puede usar en la base real: no escribe)."""
        self.usar(base)
        v = self.valor("SELECT MIN(id_vehiculo) FROM vehiculos")
        if v is None:
            self.log("   · sin vehículos: se omiten las lecturas")
            return
        for nombre, args in (("sp_obtener_vehiculos", ()), ("sp_obtener_vehiculo", (v,)),
                             ("sp_obtener_comandos_vehiculo", (v,)), ("sp_obtener_estado", (v,)),
                             ("sp_obtener_historial", (v,)), ("sp_obtener_demos", (v,))):
            self.llamar(nombre, args)
        d = self.valor("SELECT MIN(id_demo) FROM demos")
        if d is not None:
            self.llamar("sp_obtener_movimientos_demo", (d,))
        self.log("   ✓ los 7 SP de consulta responden")

    def probar_escrituras(self, base):
        """Los SP de escritura siguen funcionando con las columnas nuevas (SOLO en la copia)."""
        self._proteger(base, produccion=False)
        self.usar(base)
        antes = self.conteos(base)
        v = int(self.llamar("sp_crear_vehiculo", ("Prueba de migración", "Modelo de prueba",
                                                  "Creado y borrado por app.db.migrar probar", "ESP32"))[0]["id_vehiculo"])
        fila = self.llamar("sp_obtener_vehiculo", (v,))[0]
        if "estado_comercial" in fila and fila["estado_comercial"] != "inventario":
            raise ErrorMigracion(f"sp_crear_vehiculo: estado_comercial inesperado «{fila['estado_comercial']}»")
        c = int(self.llamar("sp_crear_comando", (v, "DETENER", 9, "Prueba"))[0]["id_comando"])
        self.llamar("sp_actualizar_comando", (c, "DETENER", 9, "Prueba editada", 1))
        c2 = int(self.llamar("sp_crear_comando", (v, "LUZ", 10, None))[0]["id_comando"])
        self.llamar("sp_eliminar_comando", (c2,))
        self.llamar("sp_actualizar_estado", (v, c, 0))
        self.llamar("sp_registrar_historial", (v, c, "PRUEBA_MIGRACION"))
        self.llamar("sp_obtener_historial", (v,))
        d = int(self.llamar("sp_crear_demo", (v, "Demo de prueba", None))[0]["id_demo"])
        demo = next(x for x in self.llamar("sp_obtener_demos", (v,)) if x["id_demo"] == d)
        if "ambito" in demo and demo["ambito"] != "fabrica":
            raise ErrorMigracion(f"sp_crear_demo: ámbito inesperado «{demo['ambito']}»")
        self.llamar("sp_actualizar_demo", (d, "Demo de prueba", "editada", 1))
        self.llamar("sp_agregar_movimiento_demo", (d, c, 1, 500, 0))
        paso = self.llamar("sp_obtener_movimientos_demo", (d,))[0]["id_demo_movimiento"]
        self.llamar("sp_actualizar_movimiento_demo", (paso, c, 1, 600, 0))
        self.llamar("sp_actualizar_vehiculo", (v, "Prueba de migración (editada)", "Modelo de prueba", "x", "ESP32", 1))
        # Borrado en orden seguro (paso → DEMO → vehículo): ver diagnóstico de cascada.
        self.llamar("sp_eliminar_movimiento_demo", (paso,))
        self.llamar("sp_eliminar_demo", (d,))
        self.llamar("sp_eliminar_vehiculo", (v,))
        despues = self.conteos(base)
        if antes != despues:
            raise ErrorMigracion(f"Los SP de escritura dejaron registros: {antes} → {despues}")
        self.log("   ✓ los 14 SP de escritura funcionan y no dejan registros")

    def diagnostico_cascada(self, base):
        """Informativo: ¿se puede eliminar una unidad que tiene DEMO con pasos? (comportamiento previo)."""
        self._proteger(base, produccion=False)
        self.usar(base)
        v = int(self.llamar("sp_crear_vehiculo", ("Prueba cascada", None, None, None))[0]["id_vehiculo"])
        c = int(self.llamar("sp_crear_comando", (v, "AVANZAR", 1, None))[0]["id_comando"])
        d = int(self.llamar("sp_crear_demo", (v, "Demo cascada", None))[0]["id_demo"])
        self.llamar("sp_agregar_movimiento_demo", (d, c, 1, 500, 0))
        try:
            self.llamar("sp_eliminar_vehiculo", (v,))
            return "se elimina en cascada (comandos, DEMO, pasos, estado e historial de esa unidad)"
        except mysql.connector.Error as error:
            self.ejecutar("DELETE FROM demo_movimientos WHERE id_demo = %s", (d,))
            self.llamar("sp_eliminar_vehiculo", (v,))
            return f"FALLA con {error.errno} ({error.msg}): hay que borrar antes los pasos de sus DEMO"


# ============================ Comandos ============================

def base_administrativa():
    """Database con la cuenta de administración (DB_MIGRA_USER/DB_MIGRA_PASSWORD si existen en .env).

    Así la API puede usar una cuenta con solo EXECUTE (DB_USER) y las migraciones otra con DDL.
    """
    db = Database()
    usuario, clave = os.getenv("DB_MIGRA_USER"), os.getenv("DB_MIGRA_PASSWORD")
    if usuario and clave:
        db.config = dataclasses.replace(db.config, db_user=usuario, db_password=clave)
    return db


def _conectar():
    db = base_administrativa()
    conexion = db.get_connection()
    return db, conexion


def _diferencias(a, b):
    lineas = []
    for tabla in sorted(set(a) | set(b)):
        for parte in ("columnas", "indices", "llaves", "checks"):
            x, y = a.get(tabla, {}).get(parte), b.get(tabla, {}).get(parte)
            if x != y:
                lineas.append(f"{tabla}.{parte}: antes={x} · después={y}")
    return lineas


def _probar_versiones(ex, copia, versiones):
    """Pruebas propias de cada versión (app/db/pruebas_procedimientos.py), solo en la copia."""
    for m in versiones:
        prueba = PRUEBAS.get(m.version)
        if prueba:
            ex._proteger(copia, produccion=False)
            prueba(ex, copia)
            ex.log(f"   ✓ pruebas de los procedimientos de {m.version}")


def _guardar_informe(ex, nombre):
    CARPETA_DIAGNOSTICO.mkdir(exist_ok=True)
    destino = CARPETA_DIAGNOSTICO / f"{nombre}_{datetime.now():%Y%m%d_%H%M%S}.md"
    destino.write_text("\n".join(ex.lineas) + "\n", encoding="utf-8")
    return destino


def cmd_plan(_args):
    for m in cargar_migraciones():
        print(f"{m.version} {m.descripcion}")
        print(f"   UP:   {len(m.up.sentencias)} sentencias · {len(m.up.previos)} previas · "
              f"{len(m.up.verificaciones)} verificaciones · sha256 {m.checksum[:16]}…")
        print(f"   DOWN: {len(m.down.sentencias)} sentencias "
              f"({sum(1 for s in m.down.sentencias if s.condiciones)} condicionales)")
    print("OK: archivos válidos")


def cmd_estado(_args):
    migraciones = cargar_migraciones()
    db, con = _conectar()
    try:
        ex = Ejecutor(con, db.config.db_name)
        ex.preparar_sesion()
        hechas = ex.aplicadas(db.config.db_name)
        for m in migraciones:
            if m.version in hechas:
                marca = "aplicada" + ("" if hechas[m.version] == m.checksum else "  ⚠ el archivo cambió después de aplicarse")
            else:
                marca = "PENDIENTE"
            print(f"{m.version} {m.descripcion:40} {marca}")
    finally:
        con.close()


def cmd_probar(args):
    migraciones = cargar_migraciones()
    db, con = _conectar()
    real = db.config.db_name
    copia = real + SUFIJO_COPIA
    ex = Ejecutor(con, real)
    exito = False
    try:
        ex.preparar_sesion()
        ex.log(f"# Prueba de migraciones · copia «{copia}» de «{real}»")
        ex.log(f"Fecha: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC · {len(migraciones)} migraciones · "
               f"MySQL {ex.valor('SELECT VERSION()')}")
        ex.log("La base real solo se LEE durante esta prueba.")
        ex.log()
        faltan = PROCEDIMIENTOS_ORIGINALES - ex.procedimientos(real)
        if faltan:
            raise ErrorMigracion(f"La base real no tiene los 21 SP: faltan {sorted(faltan)}")
        conteo_real = ex.conteos(real)
        ex.log("## 1. Copia")
        ex.crear_copia(real, copia)
        hechas = ex.aplicadas(copia)
        for m in migraciones:
            if m.version in hechas and hechas[m.version] != m.checksum:
                raise ErrorMigracion(f"{m.version} ya está aplicada en la base real, pero su archivo cambió después.")
        pendientes = [m for m in migraciones if m.version not in hechas]
        previas = sorted(ex.tablas(copia) - {TABLA_HISTORIAL, MARCA_COPIA})
        base_estructura = ex.estructura(copia, previas)
        base_procedimientos = ex.procedimientos(copia)
        base_conteos = ex.conteos(copia)
        ex.log(f"   ✓ copia creada · {len(previas)} tablas · registros: {base_conteos}")
        ex.log(f"   · ya aplicadas en la base real: {sorted(hechas) or 'ninguna'} · por probar: "
               f"{[m.version for m in pendientes] or 'ninguna'}")
        if base_conteos != conteo_real:
            ex.log(f"   · la base real cambió mientras se copiaba (normal si la API está en uso): {conteo_real}")
        ex.log(f"   · diagnóstico: eliminar una unidad con DEMO y pasos → {ex.diagnostico_cascada(copia)}")
        ex.log()
        ex.log("## 2. Aplicar las migraciones pendientes")
        for m in pendientes:
            ex.aplicar_up(copia, m, respaldo="prueba")
        ex.log()
        ex.log("## 3. Compatibilidad con los 21 SP existentes y pruebas de los nuevos")
        ex.probar_lecturas(copia)
        ex.probar_escrituras(copia)
        _probar_versiones(ex, copia, pendientes)
        ex.log()
        ex.log("## 4. Revertir lo aplicado (de la más nueva a la más antigua)")
        for m in reversed(pendientes):
            ex.aplicar_down(copia, m)
        diferencias = _diferencias(base_estructura, ex.estructura(copia, previas))
        if diferencias:
            raise ErrorMigracion("La reversión no dejó la estructura original:\n   " + "\n   ".join(diferencias))
        sobrantes = ex.tablas(copia) - set(previas) - {TABLA_HISTORIAL, MARCA_COPIA}
        if sobrantes:
            raise ErrorMigracion(f"Quedaron tablas tras la reversión: {sorted(sobrantes)}")
        if ex.conteos(copia) != base_conteos:
            raise ErrorMigracion("La reversión cambió el número de registros")
        if ex.procedimientos(copia) != base_procedimientos:
            raise ErrorMigracion("La reversión no dejó los mismos procedimientos: "
                                 f"sobran {sorted(ex.procedimientos(copia) - base_procedimientos)}, "
                                 f"faltan {sorted(base_procedimientos - ex.procedimientos(copia))}")
        ex.log(f"   ✓ estructura de las {len(previas)} tablas previas idéntica a la inicial · registros iguales · "
               f"sin tablas sobrantes · mismos {len(base_procedimientos)} procedimientos")
        ex.log()
        ex.log("## 5. Volver a aplicar (la reversión deja la base lista para reintentar)")
        for m in pendientes:
            ex.aplicar_up(copia, m, respaldo="prueba")
        ex.probar_lecturas(copia)
        ex.probar_escrituras(copia)
        _probar_versiones(ex, copia, pendientes)
        if ex.conteos(copia) != base_conteos:
            raise ErrorMigracion("La segunda aplicación cambió el número de registros")
        ex.log()
        exito = True
    except Exception as error:                       # todo error, previsto o no, queda en el informe
        ex.log()
        ex.log(f"## ✗ FALLA ({error.__class__.__name__})\n{error}")
        ex.log(f"La copia «{copia}» se conserva para revisarla. Bórrala con: python -m app.db.migrar limpiar-copia")
    finally:
        try:
            if exito and not args.conservar_copia:
                ex.borrar_copia(copia)
                ex.log(f"## 6. Copia «{copia}» borrada")
        finally:
            con.close()

    if exito:
        CARPETA_DIAGNOSTICO.mkdir(exist_ok=True)
        SELLO_PRUEBA.write_text(json.dumps({
            "fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "base": real,
            "migraciones": {m.version: m.checksum for m in migraciones},
        }, indent=2), encoding="utf-8")
        ex.log("")
        ex.log("RESULTADO: ✓ PASÓ. Ya se puede aplicar en la base real (con respaldo).")
    else:
        ex.log("")
        ex.log("RESULTADO: ✗ NO PASÓ. No apliques nada en la base real.")
    destino = _guardar_informe(ex, "prueba_migraciones")
    print(f"\nInforme: {destino}")
    sys.exit(0 if exito else 1)


def cmd_aplicar(args):
    migraciones = cargar_migraciones()
    if not args.respaldo.strip():
        raise ErrorMigracion("Indica el respaldo: --respaldo <identificador del snapshot de RDS>")
    if not SELLO_PRUEBA.exists():
        raise ErrorMigracion("Primero ejecuta `python -m app.db.migrar probar` y revisa que pase.")
    sello = json.loads(SELLO_PRUEBA.read_text(encoding="utf-8"))
    db, con = _conectar()
    real = db.config.db_name
    ex = Ejecutor(con, real)
    try:
        ex.preparar_sesion()
        hechas = ex.aplicadas(real)
        pendientes = [m for m in migraciones if m.version not in hechas and (not args.hasta or m.version <= args.hasta)]
        if not pendientes:
            print("No hay migraciones pendientes.")
            return
        for m in pendientes:
            if sello.get("migraciones", {}).get(m.version) != m.checksum:
                raise ErrorMigracion(f"{m.version} no es el archivo que pasó la prueba: vuelve a ejecutar `probar`.")
        faltan = PROCEDIMIENTOS_ORIGINALES - ex.procedimientos(real)
        if faltan:
            raise ErrorMigracion(f"La base real no tiene los 21 SP: faltan {sorted(faltan)}")
        ex.log(f"# Aplicación en «{real}» · respaldo: {args.respaldo}")
        ex.log(f"Fecha: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC · registros antes: {ex.conteos(real)}")
        for m in pendientes:
            ex.aplicar_up(real, m, respaldo=args.respaldo, produccion=True)
        ex.probar_lecturas(real)
        ex.log(f"Registros después: {ex.conteos(real)}")
        ex.log("RESULTADO: ✓ aplicado")
    except (ErrorMigracion, mysql.connector.Error) as error:
        ex.log(f"✗ FALLA: {error}")
        ex.log("Revisa el mensaje: si una migración quedó a medias, revierte esa versión o restaura el respaldo.")
        raise SystemExit(1)
    finally:
        con.close()
        print(f"Informe: {_guardar_informe(ex, 'aplicacion_migraciones')}")


def cmd_revertir(args):
    migraciones = {m.version: m for m in cargar_migraciones()}
    if args.version not in migraciones:
        raise ErrorMigracion(f"No existe la versión {args.version}")
    db, con = _conectar()
    real = db.config.db_name
    base = args.base or real
    produccion = base == real
    if produccion and not (args.confirmo_produccion and args.respaldo):
        raise ErrorMigracion("Revertir en la base REAL borra los datos de las tablas nuevas. "
                             "Requiere --confirmo-produccion y --respaldo <id>.")
    ex = Ejecutor(con, real)
    try:
        ex.preparar_sesion()
        hechas = ex.aplicadas(base)
        objetivo = [migraciones[v] for v in sorted(hechas, reverse=True) if v >= args.version and v in migraciones]
        if not objetivo:
            print("No hay migraciones aplicadas desde esa versión.")
            return
        ex.log(f"# Reversión en «{base}» desde {args.version}" + (f" · respaldo: {args.respaldo}" if produccion else ""))
        for m in objetivo:
            ex.aplicar_down(base, m, produccion=produccion)
        ex.log("RESULTADO: ✓ revertido")
    finally:
        con.close()
        print(f"Informe: {_guardar_informe(ex, 'reversion_migraciones')}")


def cmd_limpiar(_args):
    db, con = _conectar()
    try:
        ex = Ejecutor(con, db.config.db_name)
        ex.preparar_sesion()
        copia = db.config.db_name + SUFIJO_COPIA
        if not ex.valor("SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s", (copia,)):
            print("No hay copia de prueba.")
            return
        ex.borrar_copia(copia)
        print(f"Copia «{copia}» borrada.")
    finally:
        con.close()


def cmd_crear_cuenta_api(args):
    """Cuenta de la API con privilegios mínimos: solo EXECUTE (los SP son SQL SECURITY DEFINER)."""
    if not re.fullmatch(r"[a-z_][a-z0-9_]{2,31}", args.usuario):
        raise ErrorMigracion("Nombre de cuenta inválido (minúsculas, números y _).")
    db, con = _conectar()
    base = db.config.db_name
    if args.usuario == db.config.db_user:
        raise ErrorMigracion("Esa es la cuenta con la que te conectas ahora; elige otro nombre.")
    clave = secrets.token_urlsafe(24) + "-Aa9"          # aleatoria; se muestra UNA vez y no se guarda
    ex = Ejecutor(con, base)
    try:
        ex.preparar_sesion()
        existe = ex.valor("SELECT COUNT(*) FROM mysql.user WHERE user = %s AND host = '%'", (args.usuario,))
        if existe and not args.rotar:
            raise ErrorMigracion(f"La cuenta {args.usuario} ya existe. Usa --rotar para cambiarle la contraseña.")
        if existe:
            ex.ejecutar(f"ALTER USER '{args.usuario}'@'%' IDENTIFIED BY %s", (clave,))
        else:
            ex.ejecutar(f"CREATE USER '{args.usuario}'@'%' IDENTIFIED BY %s", (clave,))
        ex.ejecutar(f"GRANT EXECUTE ON {_id(base)}.* TO '{args.usuario}'@'%'")
    finally:
        con.close()

    # Comprobación: la cuenta nueva ejecuta SP pero NO puede leer tablas directamente.
    prueba = Database()
    prueba.config = dataclasses.replace(db.config, db_user=args.usuario, db_password=clave)
    c2 = prueba.get_connection()
    try:
        cursor = c2.cursor()
        cursor.callproc("sp_obtener_vehiculos")
        for r in cursor.stored_results():
            r.fetchall()
        cursor.close()
        cursor = c2.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM vehiculos")
            cursor.fetchall()
            raise ErrorMigracion("La cuenta nueva puede leer tablas directamente: revisa sus privilegios.")
        except mysql.connector.Error as error:
            if error.errno != 1142:                        # 1142 = SELECT denegado: es lo esperado
                raise
        finally:
            cursor.close()
    finally:
        c2.close()

    print(f"✓ Cuenta {args.usuario}: ejecuta los procedimientos y no puede leer tablas directamente.")
    print("\nContraseña (se muestra solo esta vez):")
    print(f"   {clave}")
    print("\nEdita C:\\vehiculo_oit\\.env así y reinicia la API (Stop/Start-ScheduledTask VehiculoAPI):")
    print(f"   DB_MIGRA_USER={db.config.db_user}        <- la cuenta administrativa actual (migraciones)")
    print("   DB_MIGRA_PASSWORD=<la contraseña actual de DB_PASSWORD>")
    print(f"   DB_USER={args.usuario}")
    print("   DB_PASSWORD=<la contraseña de arriba>")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m app.db.migrar", description="Migraciones versionadas de RDS.")
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("plan", help="valida los archivos (sin conectarse)").set_defaults(f=cmd_plan)
    sub.add_parser("estado", help="aplicadas y pendientes en la base real").set_defaults(f=cmd_estado)
    pr = sub.add_parser("probar", help="prueba completa en una copia de la base")
    pr.add_argument("--conservar-copia", action="store_true")
    pr.set_defaults(f=cmd_probar)
    ap = sub.add_parser("aplicar", help="aplica las pendientes en la base real")
    ap.add_argument("--respaldo", required=True, help="identificador del snapshot de RDS tomado antes")
    ap.add_argument("--hasta", help="última versión a aplicar (p. ej. V003)")
    ap.set_defaults(f=cmd_aplicar)
    rv = sub.add_parser("revertir", help="revierte desde una versión")
    rv.add_argument("version")
    rv.add_argument("--base")
    rv.add_argument("--confirmo-produccion", action="store_true")
    rv.add_argument("--respaldo", default="")
    rv.set_defaults(f=cmd_revertir)
    sub.add_parser("limpiar-copia", help="borra la copia de prueba").set_defaults(f=cmd_limpiar)
    cc = sub.add_parser("crear-cuenta-api", help="crea la cuenta de la API con solo EXECUTE (hallazgo H12)")
    cc.add_argument("--usuario", default="vehiculo_api")
    cc.add_argument("--rotar", action="store_true", help="si ya existe, le cambia la contraseña")
    cc.set_defaults(f=cmd_crear_cuenta_api)
    args = p.parse_args(argv)
    for flujo in (sys.stdout, sys.stderr):          # la consola de Windows puede no tener ✓ ✗ →
        try:
            flujo.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        args.f(args)
    except ErrorMigracion as error:
        print(f"✗ {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
