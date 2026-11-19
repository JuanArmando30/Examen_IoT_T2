-- =====================================================================
-- V010 · REVERSIÓN · Autenticación
-- Borra los 14 SP de V010 y deja sp_version_esquema devolviendo 9.
-- Las tablas (usuarios, tokens, códigos) son de V002 y no se tocan.
-- =====================================================================

DROP PROCEDURE IF EXISTS sp_registrar_historial_autor;
DROP PROCEDURE IF EXISTS sp_soporte_listar;
DROP PROCEDURE IF EXISTS sp_soporte_revocar;
DROP PROCEDURE IF EXISTS sp_soporte_otorgar;
DROP PROCEDURE IF EXISTS sp_acceso_unidad;
DROP PROCEDURE IF EXISTS sp_codigo_usar;
DROP PROCEDURE IF EXISTS sp_codigo_crear;
DROP PROCEDURE IF EXISTS sp_token_revocar;
DROP PROCEDURE IF EXISTS sp_token_usar;
DROP PROCEDURE IF EXISTS sp_token_crear;
DROP PROCEDURE IF EXISTS sp_cambiar_contrasena;
DROP PROCEDURE IF EXISTS sp_obtener_usuario_auth;
DROP PROCEDURE IF EXISTS sp_login_resultado;
DROP PROCEDURE IF EXISTS sp_login_obtener;
DROP PROCEDURE IF EXISTS sp_version_esquema;

DELIMITER $$

CREATE PROCEDURE sp_version_esquema()
BEGIN
  SELECT 9 AS version;
END$$

DELIMITER ;
