-- =====================================================================
-- V007 · Bitácora de auditoría
-- Proyecto ADMINISTRACIÓN · Etapa 2
--
-- Registra altas, asignaciones, cambios de rol, DEMO, autorizaciones de
-- soporte, inicios de sesión fallidos y accesos denegados.
-- Solo inserción: no habrá SP de UPDATE ni DELETE sobre esta tabla y la
-- cuenta de la API solo tendrá EXECUTE (ver 02-modelo-datos.md §7).
-- (No se usan triggers: con el registro binario de RDS activo pueden
-- requerir log_bin_trust_function_creators.)
-- detalle: JSON sin secretos (nunca contraseñas, tokens ni códigos).
-- Tabla nueva, vacía.
-- Reversión: V007__auditoria.down.sql
-- =====================================================================

-- @previo existe tabla usuarios
-- @previo no-existe tabla auditoria

CREATE TABLE auditoria (
  id_auditoria BIGINT       NOT NULL AUTO_INCREMENT,
  ocurrido_en  TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  id_usuario   INT          DEFAULT NULL,
  rol_actor    VARCHAR(12)  NOT NULL,
  accion       VARCHAR(60)  NOT NULL,        -- p. ej. unidad.crear, asignacion.crear, rol.cambiar, demo.editar
  recurso_tipo VARCHAR(30)  DEFAULT NULL,
  recurso_id   VARCHAR(40)  DEFAULT NULL,
  resultado    VARCHAR(10)  NOT NULL DEFAULT 'ok',
  detalle      JSON         DEFAULT NULL,
  red_hash     CHAR(64) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
  PRIMARY KEY (id_auditoria),
  KEY ix_auditoria_fecha (ocurrido_en),
  KEY ix_auditoria_usuario (id_usuario, ocurrido_en),
  KEY ix_auditoria_recurso (recurso_tipo, recurso_id),
  CONSTRAINT fk_auditoria_usuario FOREIGN KEY (id_usuario)
    REFERENCES usuarios (id_usuario) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_auditoria_rol CHECK (rol_actor IN ('admin', 'usuario', 'invitado', 'operador', 'sistema', 'dispositivo')),
  CONSTRAINT ck_auditoria_resultado CHECK (resultado IN ('ok', 'denegado', 'error'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- @verificar SELECT COUNT(*) = 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'auditoria'
