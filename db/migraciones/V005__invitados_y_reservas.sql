-- =====================================================================
-- V005 · Sesiones de invitado (anónimas) y reservas de exhibición
-- Proyecto ADMINISTRACIÓN · Etapa 2
--
-- sesiones_invitado: el invitado NO tiene cuenta; recibe un token temporal
--   (guardado como HMAC). red_hash = HMAC de la IP, solo para límites de
--   tasa: la IP no se guarda.
-- reservas_exhibicion: una sola reserva VIGENTE por unidad (UNIQUE sobre
--   una columna generada, igual que en V003). Al caducar o al desconectarse
--   el invitado, el servidor envía DETENER y cierra la reserva (fin).
-- Que la unidad sea de exhibición (estado_comercial) lo valida el SP.
-- Tablas nuevas, vacías: no toca datos existentes.
-- Reversión: V005__invitados_y_reservas.down.sql
-- =====================================================================

-- @previo existe tabla vehiculos
-- @previo no-existe tabla sesiones_invitado
-- @previo no-existe tabla reservas_exhibicion

CREATE TABLE sesiones_invitado (
  id_sesion  INT       NOT NULL AUTO_INCREMENT,
  hash_token CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  creada_en  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expira_en  DATETIME  NOT NULL,
  ultimo_uso DATETIME  DEFAULT NULL,
  cerrada_en DATETIME  DEFAULT NULL,
  red_hash   CHAR(64) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
  PRIMARY KEY (id_sesion),
  UNIQUE KEY uq_sesion_token (hash_token),
  KEY ix_sesion_red (red_hash, creada_en),
  CONSTRAINT ck_sesion_vigencia CHECK (expira_en > creada_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE reservas_exhibicion (
  id_reserva         INT         NOT NULL AUTO_INCREMENT,
  id_vehiculo        INT         NOT NULL,
  id_sesion          INT         NOT NULL,
  inicio             TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expira_en          DATETIME    NOT NULL,
  fin                DATETIME    DEFAULT NULL,
  motivo_fin         VARCHAR(12) DEFAULT NULL,
  vehiculo_reservado INT GENERATED ALWAYS AS (IF(fin IS NULL, id_vehiculo, NULL)) STORED,
  PRIMARY KEY (id_reserva),
  UNIQUE KEY uq_reserva_vigente (vehiculo_reservado),
  KEY ix_reserva_vehiculo (id_vehiculo, inicio),
  KEY ix_reserva_sesion (id_sesion),
  CONSTRAINT fk_reserva_vehiculo FOREIGN KEY (id_vehiculo)
    REFERENCES vehiculos (id_vehiculo) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_reserva_sesion FOREIGN KEY (id_sesion)
    REFERENCES sesiones_invitado (id_sesion) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_reserva_vigencia CHECK (expira_en > inicio),
  CONSTRAINT ck_reserva_motivo CHECK (motivo_fin IS NULL OR motivo_fin IN ('expirada', 'cancelada', 'desconexion', 'admin', 'detenida'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- @verificar SELECT COUNT(*) = 2 FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ('sesiones_invitado', 'reservas_exhibicion')
