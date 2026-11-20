-- =====================================================================
-- V012 · INVITADOS y reserva temporal de la unidad de EXHIBICIÓN (Etapa 7)
--
-- 6 SP nuevos (y sp_version_esquema pasa a devolver 12). No crea ni
-- modifica tablas: usa sesiones_invitado y reservas_exhibicion de V005.
-- Creados en modo estricto.
--
--   sp_catalogo_exhibicion   catálogo público: unidades en exhibición activas
--   sp_invitado_reservar     sesión anónima + reserva EXCLUSIVA en una transacción;
--                            límites por red (hash de la IP) contados en la base
--   sp_invitado_sesion       reserva vigente de un token (o nada)
--   sp_invitado_finalizar    termina una reserva (expirada, cancelada, ...)
--   sp_invitado_cerrar_todas al arrancar la API: ninguna reserva queda sin vigilancia
--   sp_comandos_invitado     comandos activos de la unidad que el modelo permite
--                            a invitados (DETENER siempre)
--
-- Una reserva SOLO se crea sobre una unidad en estado 'exhibicion' y activa:
-- un invitado nunca puede reservar la unidad de un comprador.
-- Reversión: V012__invitados.down.sql
-- =====================================================================

-- @previo existe tabla sesiones_invitado
-- @previo existe tabla reservas_exhibicion
-- @previo existe tabla modelo_comandos
-- @previo existe columna historial_comandos.id_sesion_invitado

DELIMITER $$

DROP PROCEDURE IF EXISTS sp_version_esquema$$
CREATE PROCEDURE sp_version_esquema()
BEGIN
  SELECT 12 AS version;
END$$

-- ---------------------------------------------------------------- Catálogo público
CREATE PROCEDURE sp_catalogo_exhibicion()
BEGIN
  SELECT v.id_vehiculo, v.nombre, v.descripcion, v.es_simulada,
         m.nombre AS modelo, m.descripcion AS modelo_descripcion, m.microcontrolador,
         e.conectado, e.fecha_actualizacion,
         r.expira_en AS reservada_hasta,
         GREATEST(TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), r.expira_en), 0) AS segundos_reserva
    FROM vehiculos v
    LEFT JOIN modelos_vehiculo m    ON m.id_modelo = v.id_modelo
    LEFT JOIN estado_vehiculo e     ON e.id_vehiculo = v.id_vehiculo
    LEFT JOIN reservas_exhibicion r ON r.vehiculo_reservado = v.id_vehiculo AND r.expira_en > UTC_TIMESTAMP()
   WHERE v.estado_comercial = 'exhibicion' AND v.activo = 1
   ORDER BY v.nombre, v.id_vehiculo;
END$$

-- ---------------------------------------------------------------- Reservar
-- resultado: ok | no_disponible | ocupada | limite | enfriamiento
-- `segundos`: duración (ok) o cuánto falta para poder intentarlo (resto).
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

-- ---------------------------------------------------------------- Sesión vigente
CREATE PROCEDURE sp_invitado_sesion(IN p_hash_token CHAR(64))
BEGIN
  SELECT s.id_sesion, r.id_reserva, r.id_vehiculo, r.expira_en,
         TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), r.expira_en) AS segundos_restantes
    FROM sesiones_invitado s
    JOIN reservas_exhibicion r ON r.id_sesion = s.id_sesion
   WHERE s.hash_token = p_hash_token AND s.cerrada_en IS NULL
     AND r.fin IS NULL AND r.expira_en > UTC_TIMESTAMP();
END$$

-- ---------------------------------------------------------------- Terminar
CREATE PROCEDURE sp_invitado_finalizar(IN p_id_reserva INT, IN p_motivo VARCHAR(12))
BEGIN
  DECLARE v_finalizadas INT DEFAULT 0;
  UPDATE reservas_exhibicion SET fin = UTC_TIMESTAMP(), motivo_fin = p_motivo
   WHERE id_reserva = p_id_reserva AND fin IS NULL;
  SET v_finalizadas = ROW_COUNT();
  UPDATE sesiones_invitado s JOIN reservas_exhibicion r ON r.id_sesion = s.id_sesion
     SET s.cerrada_en = UTC_TIMESTAMP()
   WHERE r.id_reserva = p_id_reserva AND s.cerrada_en IS NULL;
  SELECT v_finalizadas AS finalizadas;
END$$

CREATE PROCEDURE sp_invitado_cerrar_todas(IN p_motivo VARCHAR(12))
BEGIN
  DECLARE v_finalizadas INT DEFAULT 0;
  UPDATE sesiones_invitado s JOIN reservas_exhibicion r ON r.id_sesion = s.id_sesion
     SET s.cerrada_en = UTC_TIMESTAMP()
   WHERE r.fin IS NULL AND s.cerrada_en IS NULL;
  UPDATE reservas_exhibicion SET fin = UTC_TIMESTAMP(), motivo_fin = p_motivo WHERE fin IS NULL;
  SET v_finalizadas = ROW_COUNT();
  SELECT v_finalizadas AS finalizadas;
END$$

-- ---------------------------------------------------------------- Comandos permitidos
CREATE PROCEDURE sp_comandos_invitado(IN p_id_vehiculo INT)
BEGIN
  SELECT c.id_comando, c.nombre, c.codigo, mc.tipo
    FROM comandos c
    JOIN vehiculos v        ON v.id_vehiculo = c.id_vehiculo
    JOIN modelo_comandos mc ON mc.id_modelo = v.id_modelo AND mc.codigo = c.codigo
   WHERE c.id_vehiculo = p_id_vehiculo AND c.activo = 1
     AND (mc.permitido_invitado = 1 OR mc.tipo = 'paro')
   ORDER BY c.codigo;
END$$

DELIMITER ;

-- @verificar SELECT COUNT(*) = 7 FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'PROCEDURE' AND ROUTINE_NAME IN ('sp_version_esquema', 'sp_catalogo_exhibicion', 'sp_invitado_reservar', 'sp_invitado_sesion', 'sp_invitado_finalizar', 'sp_invitado_cerrar_todas', 'sp_comandos_invitado')
