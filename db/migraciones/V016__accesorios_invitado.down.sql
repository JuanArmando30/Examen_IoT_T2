-- =====================================================================
-- V016 · REVERSIÓN · vuelve los accesorios a NO permitidos para invitados
-- (como los sembró V001) y deja sp_version_esquema devolviendo 15.
-- Nota: también quita el permiso a un accesorio que la empresa hubiera
-- marcado a mano antes de V016 (se puede volver a marcar en Capacidades).
-- =====================================================================

-- @si existe columna modelo_comandos.permitido_invitado
UPDATE modelo_comandos
   SET permitido_invitado = 0
 WHERE tipo = 'accesorio' AND permitido_invitado = 1;

DROP PROCEDURE IF EXISTS sp_version_esquema;

DELIMITER $$

CREATE PROCEDURE sp_version_esquema()
BEGIN
  SELECT 15 AS version;
END$$

DELIMITER ;
