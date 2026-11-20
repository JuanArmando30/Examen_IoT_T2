-- =====================================================================
-- V014 · Reserva de invitado más justa (corrección tras la Etapa 9)
--
-- Reemplaza SOLO sp_invitado_reservar (y sp_version_esquema → 14). Sin
-- cambios de tablas. Dos ajustes:
--   1. La espera entre reservas (enfriamiento) ya no se aplica si la anterior
--      terminó por DESCONEXIÓN, por reinicio de la API (detenida) o porque la
--      empresa la cerró (admin): el visitante no la usó entera. Sigue contando
--      en el límite de reservas por hora.
--   2. Si la unidad está reservada por la MISMA red, responde 'propia' (no
--      'ocupada'): la página explica que es su propia reserva (otra pestaña o
--      una pestaña recién cerrada que se libera sola en segundos).
-- Reversión: V014__reserva_invitado_justa.down.sql (vuelve a la versión de V012).
-- =====================================================================

-- @previo existe tabla reservas_exhibicion

DELIMITER $$

DROP PROCEDURE IF EXISTS sp_version_esquema$$
CREATE PROCEDURE sp_version_esquema()
BEGIN
  SELECT 14 AS version;
END$$

DROP PROCEDURE IF EXISTS sp_invitado_reservar$$
CREATE PROCEDURE sp_invitado_reservar(IN p_id_vehiculo INT, IN p_hash_token CHAR(64), IN p_red_hash CHAR(64),
                                      IN p_minutos INT, IN p_max_por_hora INT, IN p_enfriamiento_min INT)
BEGIN
  DECLARE v_estado VARCHAR(12);
  DECLARE v_activo TINYINT;
  DECLARE v_ocupada DATETIME;
  DECLARE v_red_ocupante CHAR(64);
  DECLARE v_en_hora INT DEFAULT 0;
  DECLARE v_mas_antigua DATETIME;
  DECLARE v_ultima DATETIME;
  DECLARE v_sesion INT;
  DECLARE v_reserva INT;
  DECLARE v_expira DATETIME;
  DECLARE v_resultado VARCHAR(14) DEFAULT 'ok';
  DECLARE v_segundos INT DEFAULT 0;
  DECLARE EXIT HANDLER FOR 1062
  BEGIN
    ROLLBACK;
    SELECT 'ocupada' AS resultado, NULL AS id_sesion, NULL AS id_reserva, NULL AS expira_en, 0 AS segundos;
  END;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;
  UPDATE reservas_exhibicion SET fin = UTC_TIMESTAMP(), motivo_fin = 'expirada'
   WHERE fin IS NULL AND expira_en <= UTC_TIMESTAMP();

  SELECT estado_comercial, activo INTO v_estado, v_activo
    FROM vehiculos WHERE id_vehiculo = p_id_vehiculo FOR UPDATE;

  IF v_estado IS NULL OR v_estado <> 'exhibicion' OR v_activo = 0 THEN
    SET v_resultado = 'no_disponible';
  ELSE
    SELECT r.expira_en, s.red_hash INTO v_ocupada, v_red_ocupante
      FROM reservas_exhibicion r JOIN sesiones_invitado s ON s.id_sesion = r.id_sesion
     WHERE r.vehiculo_reservado = p_id_vehiculo;
    IF v_ocupada IS NOT NULL THEN
      SET v_resultado = IF(v_red_ocupante = p_red_hash, 'propia', 'ocupada'),
          v_segundos = GREATEST(TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), v_ocupada), 0);
    ELSE
      SELECT COUNT(*), MIN(creada_en) INTO v_en_hora, v_mas_antigua
        FROM sesiones_invitado
       WHERE red_hash = p_red_hash AND creada_en > UTC_TIMESTAMP() - INTERVAL 1 HOUR;
      -- Solo cuentan para la espera las reservas que el visitante usó o cerró él mismo.
      SELECT MAX(COALESCE(r.fin, r.expira_en)) INTO v_ultima
        FROM reservas_exhibicion r JOIN sesiones_invitado s ON s.id_sesion = r.id_sesion
       WHERE s.red_hash = p_red_hash
         AND (r.motivo_fin IS NULL OR r.motivo_fin IN ('expirada', 'cancelada'));
      IF v_en_hora >= p_max_por_hora THEN
        SET v_resultado = 'limite',
            v_segundos = GREATEST(TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), v_mas_antigua + INTERVAL 1 HOUR), 1);
      ELSEIF v_ultima IS NOT NULL AND v_ultima + INTERVAL p_enfriamiento_min MINUTE > UTC_TIMESTAMP() THEN
        SET v_resultado = 'enfriamiento',
            v_segundos = GREATEST(TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), v_ultima + INTERVAL p_enfriamiento_min MINUTE), 1);
      ELSE
        SET v_expira = UTC_TIMESTAMP() + INTERVAL p_minutos MINUTE;
        INSERT INTO sesiones_invitado (hash_token, expira_en, red_hash)
        VALUES (p_hash_token, v_expira + INTERVAL 1 MINUTE, p_red_hash);
        SET v_sesion = LAST_INSERT_ID();
        INSERT INTO reservas_exhibicion (id_vehiculo, id_sesion, expira_en)
        VALUES (p_id_vehiculo, v_sesion, v_expira);
        SET v_reserva = LAST_INSERT_ID(), v_segundos = p_minutos * 60;
      END IF;
    END IF;
  END IF;
  COMMIT;

  SELECT v_resultado AS resultado, v_sesion AS id_sesion, v_reserva AS id_reserva,
         v_expira AS expira_en, v_segundos AS segundos;
END$$

DELIMITER ;

-- @verificar SELECT COUNT(*) = 2 FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'PROCEDURE' AND ROUTINE_NAME IN ('sp_version_esquema', 'sp_invitado_reservar')
