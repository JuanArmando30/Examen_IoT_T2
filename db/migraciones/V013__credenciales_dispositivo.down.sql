-- =====================================================================
-- V013 · REVERSIÓN · Credencial del dispositivo
-- Borra los 4 SP de V013 y deja sp_version_esquema devolviendo 12.
-- La tabla credenciales_dispositivo es de V008 y no se toca.
-- =====================================================================

DROP PROCEDURE IF EXISTS sp_dispositivo_estado;
DROP PROCEDURE IF EXISTS sp_dispositivo_revocar;
DROP PROCEDURE IF EXISTS sp_dispositivo_validar;
DROP PROCEDURE IF EXISTS sp_dispositivo_crear;
DROP PROCEDURE IF EXISTS sp_version_esquema;

DELIMITER $$

CREATE PROCEDURE sp_version_esquema()
BEGIN
  SELECT 12 AS version;
END$$

DELIMITER ;
