-- =====================================================================
-- V015 · Eliminar DEFINITIVAMENTE una unidad dada de baja
--
-- Antes: una unidad con historial no se podía borrar (se conserva con la
-- baja, hallazgo H13) y, una vez dada de baja, tampoco: además de la regla,
-- sus asignaciones, autorizaciones de soporte, reservas de invitado y
-- credenciales (ON DELETE RESTRICT) bloqueaban el DELETE.
--
-- Ahora: sp_eliminar_unidad_baja borra TODO lo de la unidad, en una sola
-- transacción, SOLO si está en estado 'baja' y sin asignación vigente. La
-- baja sigue siendo el paso previo obligatorio (conserva el historial hasta
-- que la empresa decide eliminarla). La auditoría (sin FK a vehículos)
-- conserva quién la eliminó y qué se borró.
-- Sin cambios de tablas. Reversión: V015__eliminar_unidad_baja.down.sql.
-- =====================================================================

-- @previo existe tabla credenciales_dispositivo
-- @previo existe tabla reservas_exhibicion
-- @previo existe tabla autorizaciones_soporte

DELIMITER $$

DROP PROCEDURE IF EXISTS sp_version_esquema$$
CREATE PROCEDURE sp_version_esquema()
BEGIN
  SELECT 15 AS version;
END$$

DROP PROCEDURE IF EXISTS sp_eliminar_unidad_baja$$
CREATE PROCEDURE sp_eliminar_unidad_baja(IN p_id_vehiculo INT)
BEGIN
  DECLARE v_estado VARCHAR(12);
  DECLARE v_vigentes INT DEFAULT 0;
  DECLARE v_historial INT DEFAULT 0;
  DECLARE v_demos INT DEFAULT 0;
  DECLARE v_asignaciones INT DEFAULT 0;
  DECLARE v_reservas INT DEFAULT 0;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;
  SELECT estado_comercial INTO v_estado FROM vehiculos WHERE id_vehiculo = p_id_vehiculo FOR UPDATE;

  IF v_estado IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La unidad no existe.';
  END IF;
  IF v_estado <> 'baja' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Solo se elimina definitivamente una unidad dada de baja.';
  END IF;
  SELECT COUNT(*) INTO v_vigentes FROM asignaciones WHERE id_vehiculo = p_id_vehiculo AND hasta IS NULL;
  IF v_vigentes > 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La unidad tiene una asignación vigente.';
  END IF;

  SELECT COUNT(*) INTO v_historial    FROM historial_comandos WHERE id_vehiculo = p_id_vehiculo;
  SELECT COUNT(*) INTO v_demos        FROM demos              WHERE id_vehiculo = p_id_vehiculo;
  SELECT COUNT(*) INTO v_asignaciones FROM asignaciones       WHERE id_vehiculo = p_id_vehiculo;
  SELECT COUNT(*) INTO v_reservas     FROM reservas_exhibicion WHERE id_vehiculo = p_id_vehiculo;

  -- Orden: primero lo que apunta a comandos con RESTRICT (pasos de DEMO).
  DELETE FROM demos                   WHERE id_vehiculo = p_id_vehiculo;   -- y sus pasos (CASCADE)
  DELETE FROM historial_comandos      WHERE id_vehiculo = p_id_vehiculo;
  DELETE FROM estado_vehiculo         WHERE id_vehiculo = p_id_vehiculo;
  DELETE FROM autorizaciones_soporte  WHERE id_vehiculo = p_id_vehiculo;
  DELETE FROM asignaciones            WHERE id_vehiculo = p_id_vehiculo;
  DELETE FROM reservas_exhibicion     WHERE id_vehiculo = p_id_vehiculo;
  DELETE FROM credenciales_dispositivo WHERE id_vehiculo = p_id_vehiculo;
  DELETE FROM comandos                WHERE id_vehiculo = p_id_vehiculo;
  DELETE FROM vehiculos               WHERE id_vehiculo = p_id_vehiculo;
  COMMIT;

  SELECT v_historial AS historial, v_demos AS demos, v_asignaciones AS asignaciones, v_reservas AS reservas;
END$$

DELIMITER ;

-- @verificar SELECT COUNT(*) = 2 FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'PROCEDURE' AND ROUTINE_NAME IN ('sp_version_esquema', 'sp_eliminar_unidad_baja')
