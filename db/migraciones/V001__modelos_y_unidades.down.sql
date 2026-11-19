-- =====================================================================
-- V001 · REVERSIÓN · Modelos comerciales y datos de la unidad física
-- Deja vehiculos exactamente como antes de V001 y borra las tablas nuevas
-- (con sus datos). Pensado para la copia de prueba; en producción solo
-- con respaldo y con app/db/migrar.py revertir --confirmo-produccion.
-- Cada sentencia se ejecuta solo si el objeto existe: sirve también para
-- limpiar una aplicación que quedó a medias.
-- =====================================================================

-- @si existe fk vehiculos.fk_vehiculo_modelo
ALTER TABLE vehiculos DROP FOREIGN KEY fk_vehiculo_modelo;

-- @si existe check vehiculos.ck_vehiculo_estado_comercial
ALTER TABLE vehiculos DROP CHECK ck_vehiculo_estado_comercial;

-- @si existe indice vehiculos.uq_vehiculo_numero_serie
ALTER TABLE vehiculos DROP INDEX uq_vehiculo_numero_serie;

-- @si existe indice vehiculos.fk_vehiculo_modelo
ALTER TABLE vehiculos DROP INDEX fk_vehiculo_modelo;

-- @si existe columna vehiculos.es_simulada
ALTER TABLE vehiculos DROP COLUMN es_simulada;

-- @si existe columna vehiculos.estado_comercial
ALTER TABLE vehiculos DROP COLUMN estado_comercial;

-- @si existe columna vehiculos.numero_serie
ALTER TABLE vehiculos DROP COLUMN numero_serie;

-- @si existe columna vehiculos.id_modelo
ALTER TABLE vehiculos DROP COLUMN id_modelo;

DROP TABLE IF EXISTS modelo_comandos;

DROP TABLE IF EXISTS modelos_vehiculo;

-- @verificar SELECT COUNT(*) = 0 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'vehiculos' AND COLUMN_NAME IN ('id_modelo', 'numero_serie', 'estado_comercial', 'es_simulada')
