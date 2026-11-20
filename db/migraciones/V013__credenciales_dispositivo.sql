-- =====================================================================
-- V013 · Credencial del DISPOSITIVO para el WebSocket por unidad (Etapa 8)
--
-- 4 SP nuevos (y sp_version_esquema pasa a devolver 13). No crea ni
-- modifica tablas: usa credenciales_dispositivo de V008 (una vigente por
-- unidad gracias a su índice único). Creados en modo estricto.
--
-- El ESP32 se identifica con un secreto propio (cabecera X-Dispositivo);
-- en la base solo se guarda su HMAC-SHA256 con TOKEN_SECRETO.
--
--   sp_dispositivo_crear     revoca la anterior y registra una nueva (transacción)
--   sp_dispositivo_validar   unidad de un secreto vigente (y marca el último uso)
--   sp_dispositivo_revocar   revoca la vigente de una unidad
--   sp_dispositivo_estado    la credencial más reciente de una unidad
-- Reversión: V013__credenciales_dispositivo.down.sql
-- =====================================================================

-- @previo existe tabla credenciales_dispositivo

DELIMITER $$

DROP PROCEDURE IF EXISTS sp_version_esquema$$
CREATE PROCEDURE sp_version_esquema()
BEGIN
  SELECT 13 AS version;
END$$

CREATE PROCEDURE sp_dispositivo_crear(IN p_id_vehiculo INT, IN p_hash CHAR(64))
BEGIN
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF NOT EXISTS (SELECT 1 FROM vehiculos WHERE id_vehiculo = p_id_vehiculo) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La unidad no existe.';
  END IF;
  START TRANSACTION;
  UPDATE credenciales_dispositivo SET revocada_en = UTC_TIMESTAMP()
   WHERE id_vehiculo = p_id_vehiculo AND revocada_en IS NULL;
  INSERT INTO credenciales_dispositivo (id_vehiculo, hash_secreto) VALUES (p_id_vehiculo, p_hash);
  COMMIT;
  SELECT LAST_INSERT_ID() AS id_credencial;
END$$

CREATE PROCEDURE sp_dispositivo_validar(IN p_hash CHAR(64))
BEGIN
  DECLARE v_id INT;
  DECLARE v_vehiculo INT;
  SELECT id_credencial, id_vehiculo INTO v_id, v_vehiculo
    FROM credenciales_dispositivo WHERE hash_secreto = p_hash AND revocada_en IS NULL;
  IF v_id IS NOT NULL THEN
    UPDATE credenciales_dispositivo SET ultimo_uso = UTC_TIMESTAMP() WHERE id_credencial = v_id;
  END IF;
  SELECT v_id AS id_credencial, v_vehiculo AS id_vehiculo FROM (SELECT 1) AS x WHERE v_id IS NOT NULL;
END$$

CREATE PROCEDURE sp_dispositivo_revocar(IN p_id_vehiculo INT)
BEGIN
  UPDATE credenciales_dispositivo SET revocada_en = UTC_TIMESTAMP()
   WHERE id_vehiculo = p_id_vehiculo AND revocada_en IS NULL;
  SELECT ROW_COUNT() AS revocadas;
END$$

CREATE PROCEDURE sp_dispositivo_estado(IN p_id_vehiculo INT)
BEGIN
  SELECT id_credencial, creada_en, ultimo_uso, revocada_en, (revocada_en IS NULL) AS vigente
    FROM credenciales_dispositivo
   WHERE id_vehiculo = p_id_vehiculo
   ORDER BY id_credencial DESC
   LIMIT 1;
END$$

DELIMITER ;

-- @verificar SELECT COUNT(*) = 5 FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'PROCEDURE' AND ROUTINE_NAME IN ('sp_version_esquema', 'sp_dispositivo_crear', 'sp_dispositivo_validar', 'sp_dispositivo_revocar', 'sp_dispositivo_estado')
