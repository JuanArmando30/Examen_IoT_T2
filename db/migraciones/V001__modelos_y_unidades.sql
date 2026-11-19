-- =====================================================================
-- V001 · Modelos comerciales y datos de la unidad física
-- Proyecto ADMINISTRACIÓN · Etapa 2
--
-- Qué hace
--   1. Crea modelos_vehiculo (el producto que se vende) y modelo_comandos
--      (capacidades reales del hardware de ese modelo).
--   2. Amplía vehiculos, que pasa a representar la UNIDAD FÍSICA, con
--      id_modelo, numero_serie, estado_comercial y es_simulada. Todas son
--      NULL o tienen DEFAULT: sp_crear_vehiculo y sp_actualizar_vehiculo
--      siguen funcionando sin cambios.
--   3. Migra los datos actuales: un modelo por cada texto distinto de
--      vehiculos.modelo; capacidades a partir del catálogo de comandos de
--      cada unidad; límites de DEMO que respetan las DEMO ya guardadas.
--
-- No borra ni modifica datos existentes: solo llena columnas NUEVAS.
-- Reversión: V001__modelos_y_unidades.down.sql
-- Directivas (las interpreta app/db/migrar.py):
--   @previo  = comprobación antes de empezar (si falla, no se ejecuta nada)
--   @si      = la siguiente sentencia solo se ejecuta si se cumple
--   @verificar = consulta que debe devolver 1 al terminar
-- =====================================================================

-- @previo existe tabla vehiculos
-- @previo existe tabla comandos
-- @previo existe tabla demos
-- @previo existe tabla demo_movimientos
-- @previo no-existe tabla modelos_vehiculo
-- @previo no-existe tabla modelo_comandos
-- @previo no-existe columna vehiculos.id_modelo

CREATE TABLE modelos_vehiculo (
  id_modelo         INT               NOT NULL AUTO_INCREMENT,
  nombre            VARCHAR(80)       NOT NULL,
  descripcion       VARCHAR(255)      DEFAULT NULL,
  microcontrolador  VARCHAR(50)       DEFAULT NULL,
  -- Límites de seguridad física que el servidor aplicará al control y a las DEMO.
  max_movimiento_ms INT UNSIGNED      NOT NULL DEFAULT 3000,    -- = DURACION_MAXIMA_INDIVIDUAL_MS del firmware
  max_paso_ms       INT UNSIGNED      NOT NULL DEFAULT 10000,
  max_pasos_demo    SMALLINT UNSIGNED NOT NULL DEFAULT 50,
  max_demo_ms       INT UNSIGNED      NOT NULL DEFAULT 300000,
  activo            TINYINT(1)        NOT NULL DEFAULT 1,
  fecha_registro    TIMESTAMP         NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id_modelo),
  UNIQUE KEY uq_modelo_nombre (nombre),
  CONSTRAINT ck_modelo_limites CHECK (
        max_movimiento_ms BETWEEN 100 AND 60000
    AND max_paso_ms       BETWEEN 100 AND 600000
    AND max_pasos_demo    BETWEEN 1 AND 500
    AND max_demo_ms       BETWEEN 1000 AND 3600000
    AND max_demo_ms      >= max_paso_ms)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE modelo_comandos (
  id_modelo_comando  INT          NOT NULL AUTO_INCREMENT,
  id_modelo          INT          NOT NULL,
  nombre             VARCHAR(60)  NOT NULL,
  codigo             INT          NOT NULL,
  descripcion        VARCHAR(255) DEFAULT NULL,
  tipo               VARCHAR(12)  NOT NULL DEFAULT 'movimiento',
  permitido_invitado TINYINT(1)   NOT NULL DEFAULT 0,
  PRIMARY KEY (id_modelo_comando),
  UNIQUE KEY uq_modelo_comando_codigo (id_modelo, codigo),
  UNIQUE KEY uq_modelo_comando_nombre (id_modelo, nombre),
  CONSTRAINT fk_modelo_comando_modelo FOREIGN KEY (id_modelo)
    REFERENCES modelos_vehiculo (id_modelo) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_modelo_comando_tipo CHECK (tipo IN ('movimiento', 'accesorio', 'paro'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE vehiculos
  ADD COLUMN id_modelo        INT         DEFAULT NULL AFTER modelo,
  ADD COLUMN numero_serie     VARCHAR(40) DEFAULT NULL AFTER id_modelo,
  ADD COLUMN estado_comercial VARCHAR(12) NOT NULL DEFAULT 'inventario' AFTER numero_serie,
  ADD COLUMN es_simulada      TINYINT(1)  NOT NULL DEFAULT 0 AFTER estado_comercial,
  ADD UNIQUE KEY uq_vehiculo_numero_serie (numero_serie),
  ADD KEY fk_vehiculo_modelo (id_modelo),
  ADD CONSTRAINT fk_vehiculo_modelo FOREIGN KEY (id_modelo)
    REFERENCES modelos_vehiculo (id_modelo) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT ck_vehiculo_estado_comercial
    CHECK (estado_comercial IN ('inventario', 'vendida', 'exhibicion', 'baja'));

-- ---------------- Migración controlada de los datos actuales ----------------

-- Un modelo por cada texto distinto de vehiculos.modelo (o el nombre si está vacío).
INSERT INTO modelos_vehiculo (nombre, descripcion, microcontrolador)
SELECT t.nombre_modelo,
       'Creado al migrar las unidades existentes (V001). Revisar nombre y microcontrolador.',
       MAX(t.microcontrolador)
  FROM (SELECT COALESCE(NULLIF(TRIM(modelo), ''), nombre) AS nombre_modelo, microcontrolador
          FROM vehiculos) AS t
 GROUP BY t.nombre_modelo;

UPDATE vehiculos v
  JOIN modelos_vehiculo m ON m.nombre = COALESCE(NULLIF(TRIM(v.modelo), ''), v.nombre)
   SET v.id_modelo = m.id_modelo
 WHERE v.id_modelo IS NULL;

-- Hoy la unidad se usa abiertamente (CONTROL_ABIERTO): equivale a una unidad de exhibición.
UPDATE vehiculos
   SET estado_comercial = IF(activo = 1, 'exhibicion', 'inventario');

-- Capacidades del modelo = códigos del catálogo actual de sus unidades.
-- Tipos según el firmware: 1-8 movimiento, DETENER paro, LUZ/SONIDO/ENCENDER_APAGAR pulsos.
INSERT INTO modelo_comandos (id_modelo, nombre, codigo, descripcion, tipo, permitido_invitado)
SELECT v.id_modelo,
       MIN(c.nombre),
       c.codigo,
       MIN(c.descripcion),
       CASE WHEN UPPER(MIN(c.nombre)) = 'DETENER' THEN 'paro'
            WHEN UPPER(MIN(c.nombre)) IN ('LUZ', 'SONIDO', 'ENCENDER_APAGAR') THEN 'accesorio'
            ELSE 'movimiento' END,
       CASE WHEN UPPER(MIN(c.nombre)) IN ('LUZ', 'SONIDO', 'ENCENDER_APAGAR') THEN 0 ELSE 1 END
  FROM comandos c
  JOIN vehiculos v ON v.id_vehiculo = c.id_vehiculo
 WHERE v.id_modelo IS NOT NULL
 GROUP BY v.id_modelo, c.codigo;

-- Los límites nunca invalidan las DEMO ya guardadas: se amplían si alguna los supera.
UPDATE modelos_vehiculo m
  JOIN (SELECT x.id_modelo,
               MAX(x.paso_max) AS paso_max,
               MAX(x.pasos)    AS pasos,
               MAX(x.total)    AS total
          FROM (SELECT v.id_modelo,
                       d.id_demo,
                       MAX(dm.duracion_ms)               AS paso_max,
                       COUNT(*)                          AS pasos,
                       SUM(dm.duracion_ms + dm.pausa_ms) AS total
                  FROM demo_movimientos dm
                  JOIN demos d     ON d.id_demo = dm.id_demo
                  JOIN vehiculos v ON v.id_vehiculo = d.id_vehiculo
                 WHERE v.id_modelo IS NOT NULL
                 GROUP BY v.id_modelo, d.id_demo) AS x
         GROUP BY x.id_modelo) AS e ON e.id_modelo = m.id_modelo
   SET m.max_paso_ms    = GREATEST(m.max_paso_ms, e.paso_max),
       m.max_pasos_demo = GREATEST(m.max_pasos_demo, e.pasos),
       m.max_demo_ms    = GREATEST(m.max_demo_ms, e.total, e.paso_max);

-- @verificar SELECT COUNT(*) = 0 FROM vehiculos WHERE id_modelo IS NULL
-- @verificar SELECT (SELECT COUNT(*) FROM (SELECT DISTINCT v.id_modelo, c.codigo FROM comandos c JOIN vehiculos v ON v.id_vehiculo = c.id_vehiculo) AS d) = (SELECT COUNT(*) FROM modelo_comandos)
-- @verificar SELECT COUNT(*) = 0 FROM vehiculos WHERE estado_comercial NOT IN ('inventario', 'vendida', 'exhibicion', 'baja')
-- @verificar SELECT COUNT(*) = 0 FROM modelo_comandos WHERE tipo = 'paro' AND permitido_invitado = 0
