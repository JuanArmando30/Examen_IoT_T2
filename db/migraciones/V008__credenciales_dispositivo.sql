-- =====================================================================
-- V008 · Credencial propia de cada dispositivo (ESP32)
-- Proyecto ADMINISTRACIÓN · Etapa 2
--
-- El firmware se conecta como CLIENTE al WSS público
-- /ws/vehiculos/{id} y ejecuta lo que llega (verificado en
-- excavadora_iot.ino). Cuando el canal deje de ser público (Etapa 8), el
-- ESP32 necesitará su propia credencial: un secreto por unidad, guardado
-- aquí como HMAC. Una sola credencial vigente por unidad (columna generada,
-- igual que en V003); rotar = revocar la anterior y emitir otra.
-- Tabla nueva, vacía. El canal actual sigue funcionando hasta actualizar
-- el firmware.
-- Reversión: V008__credenciales_dispositivo.down.sql
-- =====================================================================

-- @previo existe tabla vehiculos
-- @previo no-existe tabla credenciales_dispositivo

CREATE TABLE credenciales_dispositivo (
  id_credencial    INT       NOT NULL AUTO_INCREMENT,
  id_vehiculo      INT       NOT NULL,
  hash_secreto     CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  creada_en        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ultimo_uso       DATETIME  DEFAULT NULL,
  revocada_en      DATETIME  DEFAULT NULL,
  vehiculo_vigente INT GENERATED ALWAYS AS (IF(revocada_en IS NULL, id_vehiculo, NULL)) STORED,
  PRIMARY KEY (id_credencial),
  UNIQUE KEY uq_credencial_hash (hash_secreto),
  UNIQUE KEY uq_credencial_vigente (vehiculo_vigente),
  KEY ix_credencial_vehiculo (id_vehiculo),
  CONSTRAINT fk_credencial_vehiculo FOREIGN KEY (id_vehiculo)
    REFERENCES vehiculos (id_vehiculo) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- @verificar SELECT COUNT(*) = 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'credenciales_dispositivo'
