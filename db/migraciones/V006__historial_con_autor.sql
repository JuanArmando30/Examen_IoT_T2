-- =====================================================================
-- V006 · Historial: quién ejecutó cada movimiento + índice de consulta
-- Proyecto ADMINISTRACIÓN · Etapa 2
--
-- historial_comandos (1356+ registros) NO se reescribe: los registros
-- existentes quedan con id_usuario e id_sesion_invitado en NULL (no se
-- inventa quién los hizo). Los nuevos SP llenarán estas columnas.
-- sp_registrar_historial y sp_obtener_historial siguen funcionando igual.
--
-- Índice (id_vehiculo, fecha_hora, id_historial): permite leer los 10
-- más recientes sin ordenar todo el historial (hallazgo H8). Si MySQL lo
-- usa para la llave foránea y descarta el índice simple, la reversión lo
-- vuelve a crear.
-- Llaves SET NULL: si algún día se borrara un usuario o una sesión, el
-- movimiento se conserva (los usuarios se desactivan, no se borran).
-- Reversión: V006__historial_con_autor.down.sql
-- =====================================================================

-- @previo existe tabla historial_comandos
-- @previo existe tabla usuarios
-- @previo existe tabla sesiones_invitado
-- @previo no-existe columna historial_comandos.id_usuario
-- @previo no-existe columna historial_comandos.id_sesion_invitado
-- @previo no-existe indice historial_comandos.ix_historial_vehiculo_fecha

ALTER TABLE historial_comandos
  ADD COLUMN id_usuario         INT DEFAULT NULL AFTER origen,
  ADD COLUMN id_sesion_invitado INT DEFAULT NULL AFTER id_usuario,
  ADD KEY ix_historial_vehiculo_fecha (id_vehiculo, fecha_hora, id_historial),
  ADD KEY fk_historial_usuario (id_usuario),
  ADD KEY fk_historial_sesion (id_sesion_invitado),
  ADD CONSTRAINT fk_historial_usuario FOREIGN KEY (id_usuario)
    REFERENCES usuarios (id_usuario) ON DELETE SET NULL ON UPDATE RESTRICT,
  ADD CONSTRAINT fk_historial_sesion FOREIGN KEY (id_sesion_invitado)
    REFERENCES sesiones_invitado (id_sesion) ON DELETE SET NULL ON UPDATE RESTRICT;

-- @verificar SELECT COUNT(*) = 0 FROM historial_comandos WHERE id_usuario IS NOT NULL OR id_sesion_invitado IS NOT NULL
