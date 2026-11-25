-- =====================================================================
-- V015 · REVERSIÓN · quita sp_eliminar_unidad_baja y deja
-- sp_version_esquema devolviendo 14. (Lo ya eliminado no se recupera:
-- para eso está el snapshot de RDS tomado antes de aplicar.)
-- =====================================================================

DROP PROCEDURE IF EXISTS sp_eliminar_unidad_baja;
DROP PROCEDURE IF EXISTS sp_version_esquema;

DELIMITER $$

CREATE PROCEDURE sp_version_esquema()
BEGIN
  SELECT 14 AS version;
END$$

DELIMITER ;
