-- =====================================================================
-- V003 · Propiedad de las unidades y autorizaciones de soporte
-- Proyecto ADMINISTRACIÓN · Etapa 2
--
-- asignaciones: qué comprador tiene cada unidad y desde/hasta cuándo.
--   Una sola asignación VIGENTE por unidad: UNIQUE sobre una columna
--   generada que solo tiene valor cuando hasta IS NULL (MySQL permite
--   varios NULL en un índice único).
-- autorizaciones_soporte: consentimiento explícito y con vigencia que el
--   comprador da para que un administrador opere su unidad.
--
-- MySQL no permite ON DELETE/UPDATE CASCADE en la columna base de una
-- columna generada almacenada: por eso estas llaves usan RESTRICT. Además
-- protegen el historial comercial: no se puede borrar una unidad o un
-- usuario que tenga asignaciones.
-- Tablas nuevas, vacías: no toca datos existentes.
-- Reversión: V003__asignaciones_y_soporte.down.sql
-- =====================================================================

-- @previo existe tabla usuarios
-- @previo existe tabla vehiculos
-- @previo no-existe tabla asignaciones
-- @previo no-existe tabla autorizaciones_soporte

CREATE TABLE asignaciones (
  id_asignacion    INT         NOT NULL AUTO_INCREMENT,
  id_vehiculo      INT         NOT NULL,
  id_usuario       INT         NOT NULL,
  asignado_por     INT         NOT NULL,
  desde            DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  hasta            DATETIME    DEFAULT NULL,
  motivo_fin       VARCHAR(30) DEFAULT NULL,
  vehiculo_vigente INT GENERATED ALWAYS AS (IF(hasta IS NULL, id_vehiculo, NULL)) STORED,
  PRIMARY KEY (id_asignacion),
  UNIQUE KEY uq_asignacion_vigente (vehiculo_vigente),
  KEY ix_asignacion_vehiculo (id_vehiculo, desde),
  KEY ix_asignacion_usuario (id_usuario, hasta),
  KEY ix_asignacion_admin (asignado_por),
  CONSTRAINT fk_asignacion_vehiculo FOREIGN KEY (id_vehiculo)
    REFERENCES vehiculos (id_vehiculo) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_asignacion_usuario FOREIGN KEY (id_usuario)
    REFERENCES usuarios (id_usuario) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_asignacion_admin FOREIGN KEY (asignado_por)
    REFERENCES usuarios (id_usuario) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_asignacion_fechas CHECK (hasta IS NULL OR hasta >= desde)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE autorizaciones_soporte (
  id_autorizacion INT          NOT NULL AUTO_INCREMENT,
  id_vehiculo     INT          NOT NULL,
  otorgada_por    INT          NOT NULL,          -- comprador con asignación vigente
  otorgada_a      INT          DEFAULT NULL,      -- administrador concreto; NULL = cualquier administrador
  motivo          VARCHAR(255) NOT NULL,
  creada_en       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expira_en       DATETIME     NOT NULL,
  revocada_en     DATETIME     DEFAULT NULL,
  PRIMARY KEY (id_autorizacion),
  KEY ix_soporte_vehiculo (id_vehiculo, expira_en),
  KEY ix_soporte_otorgante (otorgada_por),
  KEY ix_soporte_admin (otorgada_a),
  CONSTRAINT fk_soporte_vehiculo FOREIGN KEY (id_vehiculo)
    REFERENCES vehiculos (id_vehiculo) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_soporte_otorgante FOREIGN KEY (otorgada_por)
    REFERENCES usuarios (id_usuario) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_soporte_admin FOREIGN KEY (otorgada_a)
    REFERENCES usuarios (id_usuario) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_soporte_vigencia CHECK (expira_en > creada_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- @verificar SELECT COUNT(*) = 2 FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ('asignaciones', 'autorizaciones_soporte')
