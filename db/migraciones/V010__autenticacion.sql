-- =====================================================================
-- V010 · Procedimientos de AUTENTICACIÓN y AUTORIZACIÓN (Etapa 4)
--
-- 14 SP nuevos (y sp_version_esquema pasa a devolver 10). Creados en modo
-- estricto. Las contraseñas llegan ya como hash Argon2id y los tokens y
-- códigos como HMAC-SHA256: la base nunca ve un secreto en claro.
-- Las operaciones sensibles son atómicas dentro del SP:
--   - rotación del token de renovación con detección de REUTILIZACIÓN
--     (si se usa un token ya usado, se revoca toda su familia)
--   - bloqueo temporal por intentos fallidos
--   - códigos de restablecimiento de un solo uso con límite de intentos
-- Los SP de token y código devuelven una columna `resultado` en lugar de
-- SIGNAL cuando necesitan CONFIRMAR un cambio (p. ej. revocar la familia)
-- antes de rechazar.
-- Reversión: V010__autenticacion.down.sql
-- =====================================================================

-- @previo existe tabla usuarios
-- @previo existe tabla tokens_renovacion
-- @previo existe tabla codigos_restablecimiento
-- @previo existe columna historial_comandos.id_usuario

DELIMITER $$

DROP PROCEDURE IF EXISTS sp_version_esquema$$
CREATE PROCEDURE sp_version_esquema()
BEGIN
  SELECT 10 AS version;
END$$

-- ---------------------------------------------------------------- Login
-- Devuelve el hash solo para verificarlo en la API (nunca sale de la API).
CREATE PROCEDURE sp_login_obtener(IN p_correo VARCHAR(254))
BEGIN
  SELECT id_usuario, correo, nombre, rol, activo, hash_contrasena, intentos_fallidos,
         bloqueado_hasta, debe_cambiar_contrasena,
         (bloqueado_hasta IS NOT NULL AND bloqueado_hasta > UTC_TIMESTAMP()) AS bloqueado
    FROM usuarios
   WHERE correo = p_correo;
END$$

-- Éxito: limpia intentos y anota el acceso. Fallo: suma un intento y, al
-- llegar al máximo, bloquea durante p_bloqueo_min minutos.
CREATE PROCEDURE sp_login_resultado(IN p_id_usuario INT, IN p_exito BOOLEAN,
                                    IN p_max_intentos INT, IN p_bloqueo_min INT)
BEGIN
  IF p_exito THEN
    UPDATE usuarios
       SET intentos_fallidos = 0, bloqueado_hasta = NULL, ultimo_acceso = UTC_TIMESTAMP()
     WHERE id_usuario = p_id_usuario;
  ELSE
    UPDATE usuarios
       SET intentos_fallidos = IF(intentos_fallidos + 1 >= p_max_intentos, 0, intentos_fallidos + 1),
           bloqueado_hasta   = IF(intentos_fallidos + 1 >= p_max_intentos,
                                  UTC_TIMESTAMP() + INTERVAL p_bloqueo_min MINUTE, bloqueado_hasta)
     WHERE id_usuario = p_id_usuario;
  END IF;
END$$

CREATE PROCEDURE sp_obtener_usuario_auth(IN p_id_usuario INT)
BEGIN
  SELECT id_usuario, correo, nombre, rol, activo, debe_cambiar_contrasena
    FROM usuarios
   WHERE id_usuario = p_id_usuario;
END$$

CREATE PROCEDURE sp_cambiar_contrasena(IN p_id_usuario INT, IN p_hash VARCHAR(255))
BEGIN
  UPDATE usuarios
     SET hash_contrasena = p_hash, debe_cambiar_contrasena = 0,
         intentos_fallidos = 0, bloqueado_hasta = NULL
   WHERE id_usuario = p_id_usuario;
  UPDATE tokens_renovacion SET revocado_en = UTC_TIMESTAMP(), motivo_revocacion = 'cambio_contrasena'
   WHERE id_usuario = p_id_usuario AND revocado_en IS NULL;
END$$

-- ---------------------------------------------------------------- Tokens de renovación
CREATE PROCEDURE sp_token_crear(IN p_id_usuario INT, IN p_hash CHAR(64), IN p_familia CHAR(32),
                                IN p_expira DATETIME, IN p_agente VARCHAR(120))
BEGIN
  INSERT INTO tokens_renovacion (id_usuario, hash_token, familia, expira_en, agente)
  VALUES (p_id_usuario, p_hash, p_familia, p_expira, p_agente);
END$$

-- Rotación: marca el token como usado y crea su reemplazo en la misma familia.
-- resultado: ok | invalido | expirado | revocado | reutilizado (familia revocada) | inactivo
CREATE PROCEDURE sp_token_usar(IN p_hash CHAR(64), IN p_nuevo_hash CHAR(64),
                               IN p_expira DATETIME, IN p_agente VARCHAR(120))
BEGIN
  DECLARE v_id BIGINT;
  DECLARE v_usuario INT;
  DECLARE v_familia CHAR(32);
  DECLARE v_expira DATETIME;
  DECLARE v_usado DATETIME;
  DECLARE v_revocado DATETIME;
  DECLARE v_activo TINYINT;
  DECLARE v_resultado VARCHAR(12) DEFAULT 'ok';
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  START TRANSACTION;
  SELECT id_token, id_usuario, familia, expira_en, usado_en, revocado_en
    INTO v_id, v_usuario, v_familia, v_expira, v_usado, v_revocado
    FROM tokens_renovacion WHERE hash_token = p_hash FOR UPDATE;
  IF v_id IS NULL THEN
    SET v_resultado = 'invalido';
  ELSEIF v_revocado IS NOT NULL THEN
    SET v_resultado = 'revocado';
  ELSEIF v_usado IS NOT NULL THEN
    -- Alguien presentó un token ya usado: posible robo. Se cierra toda la sesión.
    UPDATE tokens_renovacion SET revocado_en = UTC_TIMESTAMP(), motivo_revocacion = 'reutilizacion'
     WHERE familia = v_familia AND revocado_en IS NULL;
    SET v_resultado = 'reutilizado';
  ELSEIF v_expira <= UTC_TIMESTAMP() THEN
    SET v_resultado = 'expirado';
  ELSE
    SELECT activo INTO v_activo FROM usuarios WHERE id_usuario = v_usuario;
    IF v_activo IS NULL OR v_activo = 0 THEN
      UPDATE tokens_renovacion SET revocado_en = UTC_TIMESTAMP(), motivo_revocacion = 'usuario_inactivo'
       WHERE familia = v_familia AND revocado_en IS NULL;
      SET v_resultado = 'inactivo';
    ELSE
      UPDATE tokens_renovacion SET usado_en = UTC_TIMESTAMP() WHERE id_token = v_id;
      INSERT INTO tokens_renovacion (id_usuario, hash_token, familia, expira_en, agente)
      VALUES (v_usuario, p_nuevo_hash, v_familia, p_expira, p_agente);
    END IF;
  END IF;
  COMMIT;
  SELECT v_resultado AS resultado, u.id_usuario, u.correo, u.nombre, u.rol, u.debe_cambiar_contrasena
    FROM (SELECT 1) AS x
    LEFT JOIN usuarios u ON u.id_usuario = v_usuario AND v_resultado = 'ok';
END$$

-- Cerrar sesión: revoca la familia del token presentado (todas sus rotaciones).
CREATE PROCEDURE sp_token_revocar(IN p_hash CHAR(64))
BEGIN
  UPDATE tokens_renovacion t
    JOIN (SELECT familia FROM tokens_renovacion WHERE hash_token = p_hash) AS f ON f.familia = t.familia
     SET t.revocado_en = UTC_TIMESTAMP(), t.motivo_revocacion = 'cierre_sesion'
   WHERE t.revocado_en IS NULL;
END$$

-- ---------------------------------------------------------------- Códigos de restablecimiento
-- El nuevo código invalida los anteriores sin usar de ese usuario. Un código
-- se invalida agotando sus intentos (65535): así no se toca expira_en, que
-- debe ser siempre mayor que creado_en (CHECK de V002).
CREATE PROCEDURE sp_codigo_crear(IN p_id_usuario INT, IN p_hash CHAR(64), IN p_creado_por INT,
                                 IN p_expira DATETIME)
BEGIN
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  START TRANSACTION;
  UPDATE codigos_restablecimiento SET intentos = 65535
   WHERE id_usuario = p_id_usuario AND usado_en IS NULL AND expira_en > UTC_TIMESTAMP();
  INSERT INTO codigos_restablecimiento (id_usuario, hash_codigo, creado_por, expira_en)
  VALUES (p_id_usuario, p_hash, p_creado_por, p_expira);
  COMMIT;
END$$

-- resultado: ok | invalido | agotado (demasiados intentos: el código deja de servir)
CREATE PROCEDURE sp_codigo_usar(IN p_correo VARCHAR(254), IN p_hash CHAR(64),
                                IN p_hash_contrasena VARCHAR(255), IN p_max_intentos INT)
BEGIN
  DECLARE v_usuario INT;
  DECLARE v_codigo INT;
  DECLARE v_hash CHAR(64);
  DECLARE v_intentos INT;
  DECLARE v_resultado VARCHAR(10) DEFAULT 'invalido';
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  START TRANSACTION;
  SELECT id_usuario INTO v_usuario FROM usuarios WHERE correo = p_correo AND activo = 1;
  IF v_usuario IS NOT NULL THEN
    SELECT id_codigo, hash_codigo, intentos INTO v_codigo, v_hash, v_intentos
      FROM codigos_restablecimiento
     WHERE id_usuario = v_usuario AND usado_en IS NULL AND expira_en > UTC_TIMESTAMP()
       AND intentos < p_max_intentos
     ORDER BY id_codigo DESC LIMIT 1 FOR UPDATE;
    IF v_codigo IS NOT NULL THEN
      IF v_hash = p_hash THEN
        UPDATE codigos_restablecimiento SET usado_en = UTC_TIMESTAMP() WHERE id_codigo = v_codigo;
        UPDATE usuarios SET hash_contrasena = p_hash_contrasena, debe_cambiar_contrasena = 0,
                            intentos_fallidos = 0, bloqueado_hasta = NULL
         WHERE id_usuario = v_usuario;
        UPDATE tokens_renovacion SET revocado_en = UTC_TIMESTAMP(), motivo_revocacion = 'restablecimiento'
         WHERE id_usuario = v_usuario AND revocado_en IS NULL;
        SET v_resultado = 'ok';
      ELSEIF v_intentos + 1 >= p_max_intentos THEN
        UPDATE codigos_restablecimiento SET intentos = v_intentos + 1 WHERE id_codigo = v_codigo;
        SET v_resultado = 'agotado';
      ELSE
        UPDATE codigos_restablecimiento SET intentos = v_intentos + 1 WHERE id_codigo = v_codigo;
      END IF;
    END IF;
  END IF;
  COMMIT;
  SELECT v_resultado AS resultado, IF(v_resultado = 'ok', v_usuario, NULL) AS id_usuario;
END$$

-- ---------------------------------------------------------------- Autorización por unidad
-- Relación de un usuario con una unidad (la decisión la toma la API):
-- propietario = asignación vigente; soporte = autorización vigente del comprador.
CREATE PROCEDURE sp_acceso_unidad(IN p_id_usuario INT, IN p_id_vehiculo INT)
BEGIN
  SELECT v.id_vehiculo, v.estado_comercial, v.activo,
         EXISTS (SELECT 1 FROM asignaciones a
                  WHERE a.id_vehiculo = v.id_vehiculo AND a.id_usuario = p_id_usuario
                    AND a.hasta IS NULL) AS es_propietario,
         EXISTS (SELECT 1 FROM autorizaciones_soporte s
                  WHERE s.id_vehiculo = v.id_vehiculo AND s.revocada_en IS NULL
                    AND s.expira_en > UTC_TIMESTAMP()
                    AND (s.otorgada_a IS NULL OR s.otorgada_a = p_id_usuario)) AS soporte_vigente
    FROM vehiculos v
   WHERE v.id_vehiculo = p_id_vehiculo;
END$$

-- ---------------------------------------------------------------- Soporte (consentimiento del comprador)
-- Solo el comprador con asignación vigente puede autorizar; el permiso caduca.
CREATE PROCEDURE sp_soporte_otorgar(IN p_id_vehiculo INT, IN p_id_usuario INT, IN p_otorgada_a INT,
                                    IN p_motivo VARCHAR(255), IN p_expira DATETIME)
BEGIN
  IF NOT EXISTS (SELECT 1 FROM asignaciones
                  WHERE id_vehiculo = p_id_vehiculo AND id_usuario = p_id_usuario AND hasta IS NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Solo el comprador de la unidad puede autorizar el soporte.';
  END IF;
  IF p_otorgada_a IS NOT NULL AND NOT EXISTS (SELECT 1 FROM usuarios
                                               WHERE id_usuario = p_otorgada_a AND rol = 'admin' AND activo = 1) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El soporte solo se puede otorgar a un administrador activo.';
  END IF;
  INSERT INTO autorizaciones_soporte (id_vehiculo, otorgada_por, otorgada_a, motivo, expira_en)
  VALUES (p_id_vehiculo, p_id_usuario, p_otorgada_a, p_motivo, p_expira);
  SELECT LAST_INSERT_ID() AS id_autorizacion;
END$$

CREATE PROCEDURE sp_soporte_revocar(IN p_id_vehiculo INT, IN p_id_usuario INT)
BEGIN
  UPDATE autorizaciones_soporte SET revocada_en = UTC_TIMESTAMP()
   WHERE id_vehiculo = p_id_vehiculo AND otorgada_por = p_id_usuario AND revocada_en IS NULL;
  SELECT ROW_COUNT() AS revocadas;
END$$

CREATE PROCEDURE sp_soporte_listar(IN p_id_vehiculo INT)
BEGIN
  SELECT s.id_autorizacion, s.id_vehiculo, s.otorgada_por, s.otorgada_a, ad.nombre AS administrador,
         s.motivo, s.creada_en, s.expira_en, s.revocada_en,
         (s.revocada_en IS NULL AND s.expira_en > UTC_TIMESTAMP()) AS vigente
    FROM autorizaciones_soporte s
    LEFT JOIN usuarios ad ON ad.id_usuario = s.otorgada_a
   WHERE s.id_vehiculo = p_id_vehiculo
   ORDER BY s.creada_en DESC, s.id_autorizacion DESC
   LIMIT 20;
END$$

-- Movimiento individual con su autor (usuario o sesión de invitado).
CREATE PROCEDURE sp_registrar_historial_autor(IN p_id_vehiculo INT, IN p_id_comando INT,
                                              IN p_origen VARCHAR(30), IN p_id_usuario INT,
                                              IN p_id_sesion INT)
BEGIN
  INSERT INTO historial_comandos (id_vehiculo, id_comando, origen, id_usuario, id_sesion_invitado)
  VALUES (p_id_vehiculo, p_id_comando, p_origen, p_id_usuario, p_id_sesion);
END$$

DELIMITER ;

-- @verificar SELECT COUNT(*) = 15 FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'PROCEDURE' AND ROUTINE_NAME IN ('sp_login_obtener', 'sp_login_resultado', 'sp_obtener_usuario_auth', 'sp_cambiar_contrasena', 'sp_token_crear', 'sp_token_usar', 'sp_token_revocar', 'sp_codigo_crear', 'sp_codigo_usar', 'sp_acceso_unidad', 'sp_soporte_otorgar', 'sp_soporte_revocar', 'sp_soporte_listar', 'sp_registrar_historial_autor', 'sp_version_esquema')
