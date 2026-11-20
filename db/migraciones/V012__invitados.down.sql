-- =====================================================================
-- V012 · REVERSIÓN · Invitados
-- Borra los 6 SP de V012 y deja sp_version_esquema devolviendo 11.
-- Las tablas sesiones_invitado / reservas_exhibicion son de V005 y no se
-- tocan (el historial de reservas se conserva).
-- =====================================================================

DROP PROCEDURE IF EXISTS sp_comandos_invitado;
DROP PROCEDURE IF EXISTS sp_invitado_cerrar_todas;
DROP PROCEDURE IF EXISTS sp_invitado_finalizar;
DROP PROCEDURE IF EXISTS sp_invitado_sesion;
DROP PROCEDURE IF EXISTS sp_invitado_reservar;
DROP PROCEDURE IF EXISTS sp_catalogo_exhibicion;
DROP PROCEDURE IF EXISTS sp_version_esquema;

DELIMITER $$

CREATE PROCEDURE sp_version_esquema()
BEGIN
  SELECT 11 AS version;
END$$

DELIMITER ;
