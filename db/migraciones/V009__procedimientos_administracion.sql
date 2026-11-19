-- =====================================================================
-- V009 · Procedimientos almacenados de ADMINISTRACIÓN (Etapa 3)
--
-- 25 SP nuevos. Los 21 originales NO se modifican.
-- Se crean con el sql_mode ESTRICTO de la sesión de app/db/migrar.py:
-- un valor fuera de rango o demasiado largo da error en lugar de truncarse
-- (hallazgo H14). Son SQL SECURITY DEFINER, como los originales: la cuenta
-- de la API solo necesitará EXECUTE.
-- Las reglas de negocio que dependen del estado (asignar, finalizar,
-- crear una unidad con su catálogo) se hacen en UNA transacción dentro del
-- SP; los errores de negocio usan SIGNAL SQLSTATE '45000' (errno 1644),
-- que la API traduce a 409 con el mensaje del SP.
-- Fechas en UTC (la base y la sesión están en UTC).
-- Reversión: V009__procedimientos_administracion.down.sql
-- =====================================================================

-- @previo existe tabla modelos_vehiculo
-- @previo existe tabla usuarios
-- @previo existe tabla asignaciones
-- @previo existe tabla auditoria
-- @previo existe columna historial_comandos.id_usuario

DELIMITER $$

-- ---------------------------------------------------------------- Esquema
-- La API la consulta al arrancar: si no existe, las rutas nuevas responden
-- 503 «faltan migraciones» y el historial usa el SP original.
CREATE PROCEDURE sp_version_esquema()
BEGIN
  SELECT 9 AS version;
END$$

-- ---------------------------------------------------------------- Historial
-- Últimos N movimientos con LIMIT (usa el índice de V006; hallazgo H8).
CREATE PROCEDURE sp_obtener_historial_reciente(IN p_id_vehiculo INT, IN p_limite INT)
BEGIN
  DECLARE v_limite INT DEFAULT LEAST(GREATEST(COALESCE(p_limite, 10), 1), 100);
  SELECT h.id_historial, h.id_vehiculo, c.nombre AS comando, c.codigo, h.fecha_hora, h.origen
    FROM historial_comandos h
    LEFT JOIN comandos c ON c.id_comando = h.id_comando
   WHERE h.id_vehiculo = p_id_vehiculo
   ORDER BY h.fecha_hora DESC, h.id_historial DESC
   LIMIT v_limite;
END$$

-- ---------------------------------------------------------------- Auditoría
CREATE PROCEDURE sp_registrar_auditoria(
  IN p_id_usuario INT, IN p_rol_actor VARCHAR(12), IN p_accion VARCHAR(60),
  IN p_recurso_tipo VARCHAR(30), IN p_recurso_id VARCHAR(40), IN p_resultado VARCHAR(10),
  IN p_detalle JSON, IN p_red_hash CHAR(64))
BEGIN
  INSERT INTO auditoria (id_usuario, rol_actor, accion, recurso_tipo, recurso_id, resultado, detalle, red_hash)
  VALUES (p_id_usuario, p_rol_actor, p_accion, p_recurso_tipo, p_recurso_id,
          COALESCE(p_resultado, 'ok'), p_detalle, p_red_hash);
  SELECT LAST_INSERT_ID() AS id_auditoria;
END$$

CREATE PROCEDURE sp_listar_auditoria(
  IN p_accion VARCHAR(60), IN p_id_usuario INT, IN p_recurso_tipo VARCHAR(30),
  IN p_recurso_id VARCHAR(40), IN p_desde DATETIME, IN p_hasta DATETIME,
  IN p_limite INT, IN p_desplazamiento INT)
BEGIN
  DECLARE v_limite INT DEFAULT LEAST(GREATEST(COALESCE(p_limite, 50), 1), 200);
  DECLARE v_desplazamiento INT DEFAULT GREATEST(COALESCE(p_desplazamiento, 0), 0);
  SELECT a.id_auditoria, a.ocurrido_en, a.id_usuario, u.nombre AS usuario, a.rol_actor, a.accion,
         a.recurso_tipo, a.recurso_id, a.resultado, a.detalle, COUNT(*) OVER () AS total
    FROM auditoria a
    LEFT JOIN usuarios u ON u.id_usuario = a.id_usuario
   WHERE (p_accion IS NULL OR a.accion LIKE CONCAT(p_accion, '%'))
     AND (p_id_usuario IS NULL OR a.id_usuario = p_id_usuario)
     AND (p_recurso_tipo IS NULL OR a.recurso_tipo = p_recurso_tipo)
     AND (p_recurso_id IS NULL OR a.recurso_id = p_recurso_id)
     AND (p_desde IS NULL OR a.ocurrido_en >= p_desde)
     AND (p_hasta IS NULL OR a.ocurrido_en < p_hasta)
   ORDER BY a.ocurrido_en DESC, a.id_auditoria DESC
   LIMIT v_limite OFFSET v_desplazamiento;
END$$

-- ---------------------------------------------------------------- Métricas
CREATE PROCEDURE sp_metricas_admin()
BEGIN
  SELECT
    (SELECT COUNT(*) FROM vehiculos)                                          AS unidades,
    (SELECT COUNT(*) FROM vehiculos WHERE estado_comercial = 'inventario')    AS unidades_inventario,
    (SELECT COUNT(*) FROM vehiculos WHERE estado_comercial = 'vendida')       AS unidades_vendidas,
    (SELECT COUNT(*) FROM vehiculos WHERE estado_comercial = 'exhibicion')    AS unidades_exhibicion,
    (SELECT COUNT(*) FROM vehiculos WHERE estado_comercial = 'baja')          AS unidades_baja,
    (SELECT COUNT(*) FROM vehiculos WHERE es_simulada = 1)                    AS unidades_simuladas,
    (SELECT COUNT(*) FROM modelos_vehiculo WHERE activo = 1)                  AS modelos_activos,
    (SELECT COUNT(*) FROM usuarios WHERE rol = 'usuario' AND activo = 1)      AS clientes_activos,
    (SELECT COUNT(*) FROM usuarios WHERE rol = 'admin' AND activo = 1)        AS administradores_activos,
    (SELECT COUNT(*) FROM asignaciones WHERE hasta IS NULL)                   AS asignaciones_vigentes,
    (SELECT COUNT(*) FROM demos WHERE ambito = 'fabrica')                     AS demos_fabrica,
    (SELECT COUNT(*) FROM demos WHERE ambito = 'privada')                     AS demos_privadas,
    (SELECT COUNT(*) FROM reservas_exhibicion
      WHERE fin IS NULL AND expira_en > UTC_TIMESTAMP())                      AS reservas_vigentes,
    (SELECT COUNT(*) FROM historial_comandos
      WHERE fecha_hora >= UTC_TIMESTAMP() - INTERVAL 1 DAY)                   AS movimientos_24h,
    (SELECT COUNT(*) FROM historial_comandos
      WHERE fecha_hora >= UTC_TIMESTAMP() - INTERVAL 7 DAY)                   AS movimientos_7d,
    (SELECT COUNT(*) FROM historial_comandos)                                 AS movimientos_total,
    (SELECT MAX(fecha_hora) FROM historial_comandos)                          AS ultimo_movimiento,
    UTC_TIMESTAMP()                                                           AS generado_en;
END$$

-- ---------------------------------------------------------------- Modelos
CREATE PROCEDURE sp_listar_modelos()
BEGIN
  SELECT m.id_modelo, m.nombre, m.descripcion, m.microcontrolador, m.max_movimiento_ms,
         m.max_paso_ms, m.max_pasos_demo, m.max_demo_ms, m.activo, m.fecha_registro,
         (SELECT COUNT(*) FROM vehiculos v WHERE v.id_modelo = m.id_modelo)          AS unidades,
         (SELECT COUNT(*) FROM modelo_comandos mc WHERE mc.id_modelo = m.id_modelo)  AS capacidades
    FROM modelos_vehiculo m
   ORDER BY m.nombre;
END$$

CREATE PROCEDURE sp_obtener_modelo(IN p_id_modelo INT)
BEGIN
  SELECT m.id_modelo, m.nombre, m.descripcion, m.microcontrolador, m.max_movimiento_ms,
         m.max_paso_ms, m.max_pasos_demo, m.max_demo_ms, m.activo, m.fecha_registro,
         (SELECT COUNT(*) FROM vehiculos v WHERE v.id_modelo = m.id_modelo)          AS unidades,
         (SELECT COUNT(*) FROM modelo_comandos mc WHERE mc.id_modelo = m.id_modelo)  AS capacidades
    FROM modelos_vehiculo m
   WHERE m.id_modelo = p_id_modelo;
END$$

CREATE PROCEDURE sp_crear_modelo(
  IN p_nombre VARCHAR(80), IN p_descripcion VARCHAR(255), IN p_microcontrolador VARCHAR(50),
  IN p_max_movimiento_ms INT, IN p_max_paso_ms INT, IN p_max_pasos_demo INT, IN p_max_demo_ms INT)
BEGIN
  INSERT INTO modelos_vehiculo (nombre, descripcion, microcontrolador, max_movimiento_ms,
                                max_paso_ms, max_pasos_demo, max_demo_ms)
  VALUES (p_nombre, p_descripcion, p_microcontrolador, p_max_movimiento_ms,
          p_max_paso_ms, p_max_pasos_demo, p_max_demo_ms);
  SELECT LAST_INSERT_ID() AS id_modelo;
END$$

CREATE PROCEDURE sp_actualizar_modelo(
  IN p_id_modelo INT, IN p_nombre VARCHAR(80), IN p_descripcion VARCHAR(255),
  IN p_microcontrolador VARCHAR(50), IN p_max_movimiento_ms INT, IN p_max_paso_ms INT,
  IN p_max_pasos_demo INT, IN p_max_demo_ms INT, IN p_activo BOOLEAN)
BEGIN
  UPDATE modelos_vehiculo
     SET nombre = p_nombre, descripcion = p_descripcion, microcontrolador = p_microcontrolador,
         max_movimiento_ms = p_max_movimiento_ms, max_paso_ms = p_max_paso_ms,
         max_pasos_demo = p_max_pasos_demo, max_demo_ms = p_max_demo_ms, activo = p_activo
   WHERE id_modelo = p_id_modelo;
END$$

CREATE PROCEDURE sp_listar_capacidades(IN p_id_modelo INT)
BEGIN
  SELECT id_modelo_comando, id_modelo, nombre, codigo, descripcion, tipo, permitido_invitado
    FROM modelo_comandos
   WHERE id_modelo = p_id_modelo
   ORDER BY codigo;
END$$

-- Crea o actualiza la capacidad identificada por (modelo, código).
CREATE PROCEDURE sp_guardar_capacidad(
  IN p_id_modelo INT, IN p_nombre VARCHAR(60), IN p_codigo INT, IN p_descripcion VARCHAR(255),
  IN p_tipo VARCHAR(12), IN p_permitido_invitado BOOLEAN)
BEGIN
  INSERT INTO modelo_comandos (id_modelo, nombre, codigo, descripcion, tipo, permitido_invitado)
  VALUES (p_id_modelo, p_nombre, p_codigo, p_descripcion, p_tipo, p_permitido_invitado) AS nueva
  ON DUPLICATE KEY UPDATE nombre = nueva.nombre, descripcion = nueva.descripcion,
                          tipo = nueva.tipo, permitido_invitado = nueva.permitido_invitado;
END$$

CREATE PROCEDURE sp_eliminar_capacidad(IN p_id_modelo INT, IN p_codigo INT)
BEGIN
  DELETE FROM modelo_comandos WHERE id_modelo = p_id_modelo AND codigo = p_codigo;
END$$

-- ---------------------------------------------------------------- Unidades
CREATE PROCEDURE sp_listar_unidades(
  IN p_estado VARCHAR(12), IN p_id_modelo INT, IN p_texto VARCHAR(80),
  IN p_limite INT, IN p_desplazamiento INT)
BEGIN
  DECLARE v_limite INT DEFAULT LEAST(GREATEST(COALESCE(p_limite, 50), 1), 200);
  DECLARE v_desplazamiento INT DEFAULT GREATEST(COALESCE(p_desplazamiento, 0), 0);
  SELECT v.id_vehiculo, v.nombre, v.numero_serie, v.estado_comercial, v.es_simulada, v.activo,
         v.descripcion, v.microcontrolador, v.fecha_registro, v.id_modelo, m.nombre AS modelo,
         a.id_asignacion, a.id_usuario AS id_propietario, u.nombre AS propietario,
         u.correo AS correo_propietario, a.desde AS asignada_desde,
         e.conectado, e.fecha_actualizacion,
         COUNT(*) OVER () AS total
    FROM vehiculos v
    LEFT JOIN modelos_vehiculo m ON m.id_modelo = v.id_modelo
    LEFT JOIN asignaciones a     ON a.vehiculo_vigente = v.id_vehiculo
    LEFT JOIN usuarios u         ON u.id_usuario = a.id_usuario
    LEFT JOIN estado_vehiculo e  ON e.id_vehiculo = v.id_vehiculo
   WHERE (p_estado IS NULL OR v.estado_comercial = p_estado)
     AND (p_id_modelo IS NULL OR v.id_modelo = p_id_modelo)
     AND (p_texto IS NULL OR v.nombre LIKE CONCAT('%', p_texto, '%')
                          OR v.numero_serie LIKE CONCAT('%', p_texto, '%'))
   ORDER BY v.id_vehiculo
   LIMIT v_limite OFFSET v_desplazamiento;
END$$

CREATE PROCEDURE sp_obtener_unidad(IN p_id_vehiculo INT)
BEGIN
  SELECT v.id_vehiculo, v.nombre, v.numero_serie, v.estado_comercial, v.es_simulada, v.activo,
         v.descripcion, v.microcontrolador, v.fecha_registro, v.id_modelo, m.nombre AS modelo,
         a.id_asignacion, a.id_usuario AS id_propietario, u.nombre AS propietario,
         u.correo AS correo_propietario, a.desde AS asignada_desde,
         e.conectado, e.fecha_actualizacion
    FROM vehiculos v
    LEFT JOIN modelos_vehiculo m ON m.id_modelo = v.id_modelo
    LEFT JOIN asignaciones a     ON a.vehiculo_vigente = v.id_vehiculo
    LEFT JOIN usuarios u         ON u.id_usuario = a.id_usuario
    LEFT JOIN estado_vehiculo e  ON e.id_vehiculo = v.id_vehiculo
   WHERE v.id_vehiculo = p_id_vehiculo;
END$$

-- La unidad nace con el catálogo de comandos de su modelo (en la misma transacción).
CREATE PROCEDURE sp_crear_unidad(
  IN p_id_modelo INT, IN p_nombre VARCHAR(80), IN p_numero_serie VARCHAR(40),
  IN p_descripcion VARCHAR(255), IN p_estado VARCHAR(12), IN p_es_simulada BOOLEAN)
BEGIN
  DECLARE v_id INT;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF p_estado IS NULL OR p_estado NOT IN ('inventario', 'exhibicion') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Una unidad nueva solo puede estar en inventario o en exhibición.';
  END IF;
  START TRANSACTION;
  INSERT INTO vehiculos (nombre, modelo, id_modelo, numero_serie, estado_comercial, es_simulada,
                         descripcion, microcontrolador)
  SELECT p_nombre, m.nombre, m.id_modelo, p_numero_serie, p_estado, p_es_simulada,
         p_descripcion, m.microcontrolador
    FROM modelos_vehiculo m
   WHERE m.id_modelo = p_id_modelo AND m.activo = 1;
  IF ROW_COUNT() = 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El modelo no existe o está inactivo.';
  END IF;
  SET v_id = LAST_INSERT_ID();
  INSERT INTO comandos (id_vehiculo, nombre, codigo, descripcion)
  SELECT v_id, mc.nombre, mc.codigo, mc.descripcion
    FROM modelo_comandos mc
   WHERE mc.id_modelo = p_id_modelo;
  COMMIT;
  SELECT v_id AS id_vehiculo;
END$$

-- El estado 'vendida' solo lo ponen sp_asignar_unidad / sp_finalizar_asignacion.
CREATE PROCEDURE sp_actualizar_unidad(
  IN p_id_vehiculo INT, IN p_nombre VARCHAR(80), IN p_numero_serie VARCHAR(40),
  IN p_descripcion VARCHAR(255), IN p_estado VARCHAR(12), IN p_activo BOOLEAN)
BEGIN
  DECLARE v_actual VARCHAR(12);
  SELECT estado_comercial INTO v_actual FROM vehiculos WHERE id_vehiculo = p_id_vehiculo;
  IF v_actual IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La unidad no existe.';
  END IF;
  IF (p_estado = 'vendida') <> (v_actual = 'vendida') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El estado «vendida» solo cambia al asignar o finalizar una asignación.';
  END IF;
  UPDATE vehiculos
     SET nombre = p_nombre, numero_serie = p_numero_serie, descripcion = p_descripcion,
         estado_comercial = p_estado, activo = p_activo
   WHERE id_vehiculo = p_id_vehiculo;
END$$

-- Dar de baja en lugar de borrar: se conserva el historial (hallazgo H13).
CREATE PROCEDURE sp_baja_unidad(IN p_id_vehiculo INT)
BEGIN
  IF EXISTS (SELECT 1 FROM asignaciones WHERE id_vehiculo = p_id_vehiculo AND hasta IS NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La unidad tiene un comprador: finaliza la asignación antes de darla de baja.';
  END IF;
  IF EXISTS (SELECT 1 FROM reservas_exhibicion WHERE id_vehiculo = p_id_vehiculo AND fin IS NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La unidad tiene una reserva de exhibición vigente.';
  END IF;
  UPDATE vehiculos SET estado_comercial = 'baja', activo = 0 WHERE id_vehiculo = p_id_vehiculo;
END$$

-- ---------------------------------------------------------------- Usuarios
-- Nunca devuelven hash_contrasena.
CREATE PROCEDURE sp_listar_usuarios(
  IN p_rol VARCHAR(10), IN p_activo BOOLEAN, IN p_texto VARCHAR(100),
  IN p_limite INT, IN p_desplazamiento INT)
BEGIN
  DECLARE v_limite INT DEFAULT LEAST(GREATEST(COALESCE(p_limite, 50), 1), 200);
  DECLARE v_desplazamiento INT DEFAULT GREATEST(COALESCE(p_desplazamiento, 0), 0);
  SELECT u.id_usuario, u.correo, u.nombre, u.rol, u.activo, u.creado_en, u.ultimo_acceso,
         (u.hash_contrasena IS NOT NULL) AS tiene_contrasena,
         (SELECT COUNT(*) FROM asignaciones a WHERE a.id_usuario = u.id_usuario AND a.hasta IS NULL) AS unidades,
         COUNT(*) OVER () AS total
    FROM usuarios u
   WHERE (p_rol IS NULL OR u.rol = p_rol)
     AND (p_activo IS NULL OR u.activo = p_activo)
     AND (p_texto IS NULL OR u.nombre LIKE CONCAT('%', p_texto, '%')
                          OR u.correo LIKE CONCAT('%', p_texto, '%'))
   ORDER BY u.nombre, u.id_usuario
   LIMIT v_limite OFFSET v_desplazamiento;
END$$

CREATE PROCEDURE sp_obtener_usuario(IN p_id_usuario INT)
BEGIN
  SELECT u.id_usuario, u.correo, u.nombre, u.rol, u.activo, u.creado_en, u.ultimo_acceso,
         (u.hash_contrasena IS NOT NULL) AS tiene_contrasena,
         (SELECT COUNT(*) FROM asignaciones a WHERE a.id_usuario = u.id_usuario AND a.hasta IS NULL) AS unidades
    FROM usuarios u
   WHERE u.id_usuario = p_id_usuario;
END$$

CREATE PROCEDURE sp_crear_usuario(IN p_correo VARCHAR(254), IN p_nombre VARCHAR(100), IN p_rol VARCHAR(10))
BEGIN
  INSERT INTO usuarios (correo, nombre, rol) VALUES (p_correo, p_nombre, p_rol);
  SELECT LAST_INSERT_ID() AS id_usuario;
END$$

-- No permite dejar el sistema sin administradores activos.
CREATE PROCEDURE sp_actualizar_usuario(
  IN p_id_usuario INT, IN p_nombre VARCHAR(100), IN p_rol VARCHAR(10), IN p_activo BOOLEAN)
BEGIN
  DECLARE v_rol VARCHAR(10);
  DECLARE v_activo TINYINT;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  START TRANSACTION;
  SELECT rol, activo INTO v_rol, v_activo FROM usuarios WHERE id_usuario = p_id_usuario FOR UPDATE;
  IF v_rol IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El usuario no existe.';
  END IF;
  IF v_rol = 'admin' AND v_activo = 1 AND (p_rol <> 'admin' OR p_activo = 0)
     AND (SELECT COUNT(*) FROM usuarios WHERE rol = 'admin' AND activo = 1 AND id_usuario <> p_id_usuario) = 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Es el único administrador activo: no se puede quitar su rol ni desactivarlo.';
  END IF;
  IF p_rol <> 'usuario' AND EXISTS (SELECT 1 FROM asignaciones WHERE id_usuario = p_id_usuario AND hasta IS NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El usuario tiene unidades asignadas: finaliza esas asignaciones antes de cambiar su rol.';
  END IF;
  UPDATE usuarios SET nombre = p_nombre, rol = p_rol, activo = p_activo WHERE id_usuario = p_id_usuario;
  IF p_activo = 0 THEN
    UPDATE tokens_renovacion SET revocado_en = UTC_TIMESTAMP(), motivo_revocacion = 'usuario_desactivado'
     WHERE id_usuario = p_id_usuario AND revocado_en IS NULL;
  END IF;
  COMMIT;
END$$

-- ---------------------------------------------------------------- Asignaciones
CREATE PROCEDURE sp_listar_asignaciones(
  IN p_id_vehiculo INT, IN p_id_usuario INT, IN p_solo_vigentes BOOLEAN,
  IN p_limite INT, IN p_desplazamiento INT)
BEGIN
  DECLARE v_limite INT DEFAULT LEAST(GREATEST(COALESCE(p_limite, 50), 1), 200);
  DECLARE v_desplazamiento INT DEFAULT GREATEST(COALESCE(p_desplazamiento, 0), 0);
  SELECT a.id_asignacion, a.id_vehiculo, v.nombre AS unidad, v.numero_serie,
         a.id_usuario, u.nombre AS usuario, u.correo,
         a.asignado_por, ad.nombre AS asignado_por_nombre,
         a.desde, a.hasta, a.motivo_fin, (a.hasta IS NULL) AS vigente,
         COUNT(*) OVER () AS total
    FROM asignaciones a
    JOIN vehiculos v     ON v.id_vehiculo = a.id_vehiculo
    JOIN usuarios u      ON u.id_usuario = a.id_usuario
    LEFT JOIN usuarios ad ON ad.id_usuario = a.asignado_por
   WHERE (p_id_vehiculo IS NULL OR a.id_vehiculo = p_id_vehiculo)
     AND (p_id_usuario IS NULL OR a.id_usuario = p_id_usuario)
     AND (p_solo_vigentes IS NULL OR p_solo_vigentes = 0 OR a.hasta IS NULL)
   ORDER BY a.desde DESC, a.id_asignacion DESC
   LIMIT v_limite OFFSET v_desplazamiento;
END$$

-- Asigna la unidad a un cliente: cierra la asignación vigente (si había),
-- crea la nueva y marca la unidad como vendida, todo en una transacción.
CREATE PROCEDURE sp_asignar_unidad(IN p_id_vehiculo INT, IN p_id_usuario INT, IN p_asignado_por INT)
BEGIN
  DECLARE v_estado VARCHAR(12);
  DECLARE v_rol VARCHAR(10);
  DECLARE v_activo TINYINT;
  DECLARE v_id INT;
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
  IF v_estado = 'baja' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La unidad está dada de baja.';
  END IF;
  IF EXISTS (SELECT 1 FROM reservas_exhibicion WHERE id_vehiculo = p_id_vehiculo AND fin IS NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La unidad tiene una reserva de exhibición vigente.';
  END IF;
  SELECT rol, activo INTO v_rol, v_activo FROM usuarios WHERE id_usuario = p_id_usuario;
  IF v_rol IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El usuario no existe.';
  END IF;
  IF v_rol <> 'usuario' OR v_activo = 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Solo se puede asignar a un cliente activo.';
  END IF;
  IF EXISTS (SELECT 1 FROM asignaciones
              WHERE id_vehiculo = p_id_vehiculo AND id_usuario = p_id_usuario AND hasta IS NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La unidad ya está asignada a ese cliente.';
  END IF;
  UPDATE autorizaciones_soporte SET revocada_en = UTC_TIMESTAMP()
   WHERE id_vehiculo = p_id_vehiculo AND revocada_en IS NULL;
  UPDATE asignaciones SET hasta = UTC_TIMESTAMP(), motivo_fin = 'reasignada'
   WHERE id_vehiculo = p_id_vehiculo AND hasta IS NULL;
  INSERT INTO asignaciones (id_vehiculo, id_usuario, asignado_por, desde)
  VALUES (p_id_vehiculo, p_id_usuario, p_asignado_por, UTC_TIMESTAMP());
  SET v_id = LAST_INSERT_ID();
  UPDATE vehiculos SET estado_comercial = 'vendida' WHERE id_vehiculo = p_id_vehiculo;
  COMMIT;
  SELECT v_id AS id_asignacion;
END$$

-- Termina la asignación vigente; revoca el soporte otorgado y deja la unidad
-- en el estado indicado (inventario, exhibicion o baja).
CREATE PROCEDURE sp_finalizar_asignacion(IN p_id_asignacion INT, IN p_motivo VARCHAR(30), IN p_estado_resultante VARCHAR(12))
BEGIN
  DECLARE v_vehiculo INT;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF p_estado_resultante IS NULL OR p_estado_resultante NOT IN ('inventario', 'exhibicion', 'baja') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Estado resultante inválido (inventario, exhibicion o baja).';
  END IF;
  START TRANSACTION;
  SELECT id_vehiculo INTO v_vehiculo FROM asignaciones
   WHERE id_asignacion = p_id_asignacion AND hasta IS NULL FOR UPDATE;
  IF v_vehiculo IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La asignación no existe o ya terminó.';
  END IF;
  UPDATE asignaciones SET hasta = UTC_TIMESTAMP(), motivo_fin = COALESCE(NULLIF(TRIM(p_motivo), ''), 'finalizada')
   WHERE id_asignacion = p_id_asignacion;
  UPDATE autorizaciones_soporte SET revocada_en = UTC_TIMESTAMP()
   WHERE id_vehiculo = v_vehiculo AND revocada_en IS NULL;
  UPDATE vehiculos
     SET estado_comercial = p_estado_resultante,
         activo = IF(p_estado_resultante = 'baja', 0, activo)
   WHERE id_vehiculo = v_vehiculo;
  COMMIT;
  SELECT v_vehiculo AS id_vehiculo;
END$$

-- Unidades vigentes de un comprador (vista «Mis vehículos», Etapa 6).
CREATE PROCEDURE sp_mis_vehiculos(IN p_id_usuario INT)
BEGIN
  SELECT v.id_vehiculo, v.nombre, v.numero_serie, v.estado_comercial, v.es_simulada, v.activo,
         v.id_modelo, m.nombre AS modelo, a.id_asignacion, a.desde AS asignada_desde,
         e.conectado, e.fecha_actualizacion
    FROM asignaciones a
    JOIN vehiculos v            ON v.id_vehiculo = a.id_vehiculo
    LEFT JOIN modelos_vehiculo m ON m.id_modelo = v.id_modelo
    LEFT JOIN estado_vehiculo e  ON e.id_vehiculo = v.id_vehiculo
   WHERE a.id_usuario = p_id_usuario AND a.hasta IS NULL
   ORDER BY v.nombre, v.id_vehiculo;
END$$

DELIMITER ;

-- @verificar SELECT COUNT(*) = 25 FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'PROCEDURE' AND ROUTINE_NAME IN ('sp_version_esquema', 'sp_obtener_historial_reciente', 'sp_registrar_auditoria', 'sp_listar_auditoria', 'sp_metricas_admin', 'sp_listar_modelos', 'sp_obtener_modelo', 'sp_crear_modelo', 'sp_actualizar_modelo', 'sp_listar_capacidades', 'sp_guardar_capacidad', 'sp_eliminar_capacidad', 'sp_listar_unidades', 'sp_obtener_unidad', 'sp_crear_unidad', 'sp_actualizar_unidad', 'sp_baja_unidad', 'sp_listar_usuarios', 'sp_obtener_usuario', 'sp_crear_usuario', 'sp_actualizar_usuario', 'sp_listar_asignaciones', 'sp_asignar_unidad', 'sp_finalizar_asignacion', 'sp_mis_vehiculos')
