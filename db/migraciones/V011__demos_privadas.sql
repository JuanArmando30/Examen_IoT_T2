-- =====================================================================
-- V011 · DEMO privadas y editor de pasos (Etapa 6)
--
-- 3 SP nuevos (y sp_version_esquema pasa a devolver 11). No crea ni
-- modifica tablas: usa demos.ambito / demos.id_propietario de V004 y los
-- límites de modelos_vehiculo de V001. Creados en modo estricto.
--
--   sp_limites_unidad      límites de seguridad de la unidad (de su modelo)
--   sp_crear_demo_privada  solo el comprador con asignación vigente; máx. 20
--   sp_guardar_pasos_demo  reemplaza TODOS los pasos en una transacción,
--                          validando comando del catálogo de la unidad y
--                          activo, duración y pausa ≤ max_paso_ms,
--                          nº de pasos ≤ max_pasos_demo y total ≤ max_demo_ms.
--                          El orden es el del arreglo JSON (reordenar = guardar).
--
-- Unidades sin modelo (registradas por la ruta técnica antigua): se usan
-- los valores por defecto de V001 (3000 / 10000 / 50 / 300000).
-- Reversión: V011__demos_privadas.down.sql
-- =====================================================================

-- @previo existe columna demos.ambito
-- @previo existe columna demos.id_propietario
-- @previo existe tabla modelos_vehiculo
-- @previo existe tabla asignaciones

DELIMITER $$

DROP PROCEDURE IF EXISTS sp_version_esquema$$
CREATE PROCEDURE sp_version_esquema()
BEGIN
  SELECT 11 AS version;
END$$

-- ---------------------------------------------------------------- Límites
CREATE PROCEDURE sp_limites_unidad(IN p_id_vehiculo INT)
BEGIN
  SELECT v.id_vehiculo, v.id_modelo, m.nombre AS modelo, v.estado_comercial,
         COALESCE(m.max_movimiento_ms, 3000)  AS max_movimiento_ms,
         COALESCE(m.max_paso_ms, 10000)       AS max_paso_ms,
         COALESCE(m.max_pasos_demo, 50)       AS max_pasos_demo,
         COALESCE(m.max_demo_ms, 300000)      AS max_demo_ms
    FROM vehiculos v
    LEFT JOIN modelos_vehiculo m ON m.id_modelo = v.id_modelo
   WHERE v.id_vehiculo = p_id_vehiculo;
END$$

-- ---------------------------------------------------------------- DEMO privada
CREATE PROCEDURE sp_crear_demo_privada(IN p_id_vehiculo INT, IN p_id_usuario INT,
                                       IN p_nombre VARCHAR(80), IN p_descripcion VARCHAR(255))
BEGIN
  IF NOT EXISTS (SELECT 1 FROM asignaciones
                  WHERE id_vehiculo = p_id_vehiculo AND id_usuario = p_id_usuario AND hasta IS NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Solo el comprador de la unidad puede crear DEMO privadas en ella.';
  END IF;
  IF (SELECT COUNT(*) FROM demos
       WHERE id_vehiculo = p_id_vehiculo AND id_propietario = p_id_usuario AND ambito = 'privada') >= 20 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Máximo 20 DEMO privadas por unidad: elimina alguna antes de crear otra.';
  END IF;
  INSERT INTO demos (id_vehiculo, ambito, id_propietario, nombre, descripcion)
  VALUES (p_id_vehiculo, 'privada', p_id_usuario, p_nombre, p_descripcion);
  SELECT LAST_INSERT_ID() AS id_demo;
END$$

-- ---------------------------------------------------------------- Pasos (reemplazo atómico)
-- p_pasos: [{"id_comando": 1, "duracion_ms": 1000, "pausa_ms": 200}, ...]
CREATE PROCEDURE sp_guardar_pasos_demo(IN p_id_demo INT, IN p_pasos JSON)
BEGIN
  DECLARE v_vehiculo INT;
  DECLARE v_max_paso INT;
  DECLARE v_max_pasos INT;
  DECLARE v_max_demo INT;
  DECLARE v_pasos INT DEFAULT 0;
  DECLARE v_total BIGINT DEFAULT 0;
  DECLARE v_fuera INT DEFAULT 0;
  DECLARE v_ajenos INT DEFAULT 0;
  DECLARE v_mensaje VARCHAR(255);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  SELECT d.id_vehiculo INTO v_vehiculo FROM demos d WHERE d.id_demo = p_id_demo;
  IF v_vehiculo IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La DEMO no existe.';
  END IF;
  IF p_pasos IS NULL OR JSON_TYPE(p_pasos) <> 'ARRAY' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Los pasos deben enviarse como una lista.';
  END IF;

  SELECT COALESCE(m.max_paso_ms, 10000), COALESCE(m.max_pasos_demo, 50), COALESCE(m.max_demo_ms, 300000)
    INTO v_max_paso, v_max_pasos, v_max_demo
    FROM vehiculos v LEFT JOIN modelos_vehiculo m ON m.id_modelo = v.id_modelo
   WHERE v.id_vehiculo = v_vehiculo;

  SELECT COUNT(*),
         COALESCE(SUM(COALESCE(j.duracion_ms, 0) + COALESCE(j.pausa_ms, 0)), 0),
         COALESCE(SUM(j.duracion_ms IS NULL OR j.duracion_ms < 1 OR j.duracion_ms > v_max_paso
                      OR j.pausa_ms IS NULL OR j.pausa_ms < 0 OR j.pausa_ms > v_max_paso), 0),
         COALESCE(SUM(c.id_comando IS NULL OR c.activo = 0), 0)
    INTO v_pasos, v_total, v_fuera, v_ajenos
    FROM JSON_TABLE(p_pasos, '$[*]' COLUMNS (
           id_comando  INT PATH '$.id_comando'  NULL ON EMPTY NULL ON ERROR,
           duracion_ms INT PATH '$.duracion_ms' NULL ON EMPTY NULL ON ERROR,
           pausa_ms    INT PATH '$.pausa_ms'    DEFAULT '0' ON EMPTY NULL ON ERROR)) AS j
    LEFT JOIN comandos c ON c.id_comando = j.id_comando AND c.id_vehiculo = v_vehiculo;

  IF v_pasos > v_max_pasos THEN
    SET v_mensaje = CONCAT('La DEMO admite como máximo ', v_max_pasos, ' pasos en este modelo.');
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_mensaje;
  END IF;
  IF v_fuera > 0 THEN
    SET v_mensaje = CONCAT('Cada paso debe durar entre 1 y ', v_max_paso, ' ms (y la pausa, de 0 a ', v_max_paso, ' ms).');
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_mensaje;
  END IF;
  IF v_ajenos > 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Algún paso usa un comando inactivo o que no es de esta unidad.';
  END IF;
  IF v_total > v_max_demo THEN
    SET v_mensaje = CONCAT('La DEMO completa no puede durar más de ', v_max_demo, ' ms en este modelo.');
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_mensaje;
  END IF;

  START TRANSACTION;
  DELETE FROM demo_movimientos WHERE id_demo = p_id_demo;
  INSERT INTO demo_movimientos (id_demo, id_comando, orden, duracion_ms, pausa_ms)
  SELECT p_id_demo, j.id_comando, j.orden, j.duracion_ms, j.pausa_ms
    FROM JSON_TABLE(p_pasos, '$[*]' COLUMNS (
           orden       FOR ORDINALITY,
           id_comando  INT PATH '$.id_comando',
           duracion_ms INT PATH '$.duracion_ms',
           pausa_ms    INT PATH '$.pausa_ms' DEFAULT '0' ON EMPTY)) AS j;
  COMMIT;

  SELECT v_pasos AS pasos, v_total AS duracion_total_ms;
END$$

DELIMITER ;

-- @verificar SELECT COUNT(*) = 4 FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'PROCEDURE' AND ROUTINE_NAME IN ('sp_version_esquema', 'sp_limites_unidad', 'sp_crear_demo_privada', 'sp_guardar_pasos_demo')
