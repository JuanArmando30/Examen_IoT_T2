-- =====================================================================
-- V011 · REVERSIÓN · DEMO privadas
-- Borra los 3 SP de V011 y deja sp_version_esquema devolviendo 10.
-- Las DEMO privadas ya creadas (filas de demos con ambito='privada') se
-- CONSERVAN: son datos de los compradores. Con V010 la API no las muestra
-- en las rutas públicas porque el filtro vive en el servicio.
-- =====================================================================

DROP PROCEDURE IF EXISTS sp_guardar_pasos_demo;
DROP PROCEDURE IF EXISTS sp_crear_demo_privada;
DROP PROCEDURE IF EXISTS sp_limites_unidad;
DROP PROCEDURE IF EXISTS sp_version_esquema;

DELIMITER $$

CREATE PROCEDURE sp_version_esquema()
BEGIN
  SELECT 10 AS version;
END$$

DELIMITER ;
