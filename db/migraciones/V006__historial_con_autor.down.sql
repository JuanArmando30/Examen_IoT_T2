-- =====================================================================
-- V006 · REVERSIÓN · Historial con autor
-- Quita las columnas nuevas (y quién hizo cada movimiento nuevo). Los
-- movimientos en sí se conservan.
-- =====================================================================

-- @si existe fk historial_comandos.fk_historial_sesion
ALTER TABLE historial_comandos DROP FOREIGN KEY fk_historial_sesion;

-- @si existe fk historial_comandos.fk_historial_usuario
ALTER TABLE historial_comandos DROP FOREIGN KEY fk_historial_usuario;

-- @si existe indice historial_comandos.fk_historial_sesion
ALTER TABLE historial_comandos DROP INDEX fk_historial_sesion;

-- @si existe indice historial_comandos.fk_historial_usuario
ALTER TABLE historial_comandos DROP INDEX fk_historial_usuario;

-- Si MySQL descartó el índice simple de la llave fk_historial_vehiculo al
-- crear el compuesto, se vuelve a crear antes de quitar el compuesto.
-- @si no-existe indice historial_comandos.fk_historial_vehiculo
ALTER TABLE historial_comandos ADD KEY fk_historial_vehiculo (id_vehiculo);

-- @si existe indice historial_comandos.ix_historial_vehiculo_fecha
ALTER TABLE historial_comandos DROP INDEX ix_historial_vehiculo_fecha;

-- @si existe columna historial_comandos.id_sesion_invitado
ALTER TABLE historial_comandos DROP COLUMN id_sesion_invitado;

-- @si existe columna historial_comandos.id_usuario
ALTER TABLE historial_comandos DROP COLUMN id_usuario;
