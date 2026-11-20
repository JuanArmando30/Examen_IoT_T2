-- =====================================================================
-- V014 · REVERSIÓN · vuelve sp_invitado_reservar a su versión de V012
-- (enfriamiento tras cualquier reserva y sin el resultado 'propia') y deja
-- sp_version_esquema devolviendo 13.
-- =====================================================================

DROP PROCEDURE IF EXISTS sp_invitado_reservar;
DROP PROCEDURE IF EXISTS sp_version_esquema;

DELIMITER $$

CREATE PROCEDURE sp_version_esquema()
BEGIN
  SELECT 13 AS version;
END$$

CREATE PROCEDURE sp_invitado_reservar(IN p_id_vehiculo INT, IN p_hash_token CHAR(64), IN p_red_hash CHAR(64),
                                      IN p_minutos INT, IN p_max_por_hora INT, IN p_enfriamiento_min INT)
BEGIN
  DECLARE v_estado VARCHAR(12);
  DECLARE v_activo TINYINT;
  DECLARE v_ocupada DATETIME;
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
    -- Otro invitado reservó en el mismo instante (índice único de la reserva vigente).
    ROLLBACK;
    SELECT 'ocupada' AS resultado, NULL AS id_sesion, NULL AS id_reserva, NULL AS expira_en, 0 AS segundos;
  END;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;
  -- Las reservas vencidas se cierran aquí mismo (la API además las vigila cada segundo).
  UPDATE reservas_exhibicion SET fin = UTC_TIMESTAMP(), motivo_fin = 'expirada'
   WHERE fin IS NULL AND expira_en <= UTC_TIMESTAMP();

  SELECT estado_comercial, activo INTO v_estado, v_activo
    FROM vehiculos WHERE id_vehiculo = p_id_vehiculo FOR UPDATE;

  IF v_estado IS NULL OR v_estado <> 'exhibicion' OR v_activo = 0 THEN
    SET v_resultado = 'no_disponible';
  ELSE
    SELECT expira_en INTO v_ocupada FROM reservas_exhibicion WHERE vehiculo_reservado = p_id_vehiculo;
    IF v_ocupada IS NOT NULL THEN
      SET v_resultado = 'ocupada', v_segundos = GREATEST(TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), v_ocupada), 0);
    ELSE
      SELECT COUNT(*), MIN(creada_en) INTO v_en_hora, v_mas_antigua
        FROM sesiones_invitado
       WHERE red_hash = p_red_hash AND creada_en > UTC_TIMESTAMP() - INTERVAL 1 HOUR;
      SELECT MAX(COALESCE(r.fin, r.expira_en)) INTO v_ultima
        FROM reservas_exhibicion r JOIN sesiones_invitado s ON s.id_sesion = r.id_sesion
       WHERE s.red_hash = p_red_hash;
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
