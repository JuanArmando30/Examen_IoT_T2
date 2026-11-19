-- =====================================================================
-- V002 · Usuarios, inicio de sesión con Google (opcional), sesiones y
--        códigos de restablecimiento
-- Proyecto ADMINISTRACIÓN · Etapa 2
--
-- No existe autenticación central que reutilizar: se crea una sola tabla
-- de usuarios. El INVITADO no es una cuenta (ver V005).
-- Nada secreto se guarda en claro:
--   - hash_contrasena: Argon2id (texto ASCII del algoritmo)
--   - hash_token / hash_codigo: HMAC-SHA256 con un secreto del servidor
--     (.env), 64 caracteres hexadecimales
-- Tablas nuevas, vacías: no toca datos existentes.
-- Reversión: V002__usuarios_y_acceso.down.sql
-- =====================================================================

-- @previo no-existe tabla usuarios
-- @previo no-existe tabla identidades_externas
-- @previo no-existe tabla tokens_renovacion
-- @previo no-existe tabla codigos_restablecimiento

CREATE TABLE usuarios (
  id_usuario              INT               NOT NULL AUTO_INCREMENT,
  correo                  VARCHAR(254)      NOT NULL,
  nombre                  VARCHAR(100)      NOT NULL,
  hash_contrasena         VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,  -- NULL = solo Google
  rol                     VARCHAR(10)       NOT NULL DEFAULT 'usuario',
  activo                  TINYINT(1)        NOT NULL DEFAULT 1,
  debe_cambiar_contrasena TINYINT(1)        NOT NULL DEFAULT 0,
  intentos_fallidos       SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  bloqueado_hasta         DATETIME          DEFAULT NULL,
  creado_en               TIMESTAMP         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado_en          TIMESTAMP         NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  ultimo_acceso           DATETIME          DEFAULT NULL,
  PRIMARY KEY (id_usuario),
  UNIQUE KEY uq_usuario_correo (correo),          -- la intercalación _ai_ci ya ignora mayúsculas
  CONSTRAINT ck_usuario_rol CHECK (rol IN ('admin', 'usuario')),
  CONSTRAINT ck_usuario_correo CHECK (correo LIKE '%_@_%')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Cuentas externas vinculadas (hoy solo Google). Se vincula por el "sub"
-- de Google, nunca solo por el correo.
CREATE TABLE identidades_externas (
  id_identidad INT          NOT NULL AUTO_INCREMENT,
  id_usuario   INT          NOT NULL,
  proveedor    VARCHAR(20)  NOT NULL,
  sujeto       VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  correo       VARCHAR(254) DEFAULT NULL,
  vinculado_en TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id_identidad),
  UNIQUE KEY uq_identidad_sujeto (proveedor, sujeto),
  UNIQUE KEY uq_identidad_usuario (id_usuario, proveedor),
  CONSTRAINT fk_identidad_usuario FOREIGN KEY (id_usuario)
    REFERENCES usuarios (id_usuario) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT ck_identidad_proveedor CHECK (proveedor IN ('google'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Tokens de renovación: rotan en cada uso; "familia" = un inicio de sesión.
-- Si se reutiliza un token ya usado, se revoca toda su familia.
CREATE TABLE tokens_renovacion (
  id_token          BIGINT      NOT NULL AUTO_INCREMENT,
  id_usuario        INT         NOT NULL,
  hash_token        CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  familia           CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  emitido_en        TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expira_en         DATETIME    NOT NULL,
  usado_en          DATETIME    DEFAULT NULL,
  revocado_en       DATETIME    DEFAULT NULL,
  motivo_revocacion VARCHAR(30) DEFAULT NULL,
  agente            VARCHAR(120) DEFAULT NULL,      -- resumen del navegador (p. ej. "Chrome · Android")
  PRIMARY KEY (id_token),
  UNIQUE KEY uq_token_hash (hash_token),
  KEY ix_token_usuario (id_usuario, revocado_en),
  KEY ix_token_familia (familia),
  CONSTRAINT fk_token_usuario FOREIGN KEY (id_usuario)
    REFERENCES usuarios (id_usuario) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT ck_token_vigencia CHECK (expira_en > emitido_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Códigos de restablecimiento de un solo uso, generados por un administrador.
CREATE TABLE codigos_restablecimiento (
  id_codigo   INT               NOT NULL AUTO_INCREMENT,
  id_usuario  INT               NOT NULL,
  hash_codigo CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  creado_por  INT               NOT NULL,
  creado_en   TIMESTAMP         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expira_en   DATETIME          NOT NULL,
  usado_en    DATETIME          DEFAULT NULL,
  intentos    SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (id_codigo),
  UNIQUE KEY uq_codigo_hash (hash_codigo),
  KEY ix_codigo_usuario (id_usuario, usado_en),
  KEY ix_codigo_creador (creado_por),
  CONSTRAINT fk_codigo_usuario FOREIGN KEY (id_usuario)
    REFERENCES usuarios (id_usuario) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT fk_codigo_creador FOREIGN KEY (creado_por)
    REFERENCES usuarios (id_usuario) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_codigo_vigencia CHECK (expira_en > creado_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- @verificar SELECT COUNT(*) = 4 FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ('usuarios', 'identidades_externas', 'tokens_renovacion', 'codigos_restablecimiento')
