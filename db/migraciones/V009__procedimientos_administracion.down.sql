-- =====================================================================
-- V009 · REVERSIÓN · Procedimientos de ADMINISTRACIÓN
-- Borra solo los 25 SP nuevos; los 21 originales no se tocan.
-- La API detecta que falta sp_version_esquema y desactiva las rutas
-- nuevas (503) sin afectar Control ni Monitoreo.
-- =====================================================================

DROP PROCEDURE IF EXISTS sp_mis_vehiculos;
DROP PROCEDURE IF EXISTS sp_finalizar_asignacion;
DROP PROCEDURE IF EXISTS sp_asignar_unidad;
DROP PROCEDURE IF EXISTS sp_listar_asignaciones;
DROP PROCEDURE IF EXISTS sp_actualizar_usuario;
DROP PROCEDURE IF EXISTS sp_crear_usuario;
DROP PROCEDURE IF EXISTS sp_obtener_usuario;
DROP PROCEDURE IF EXISTS sp_listar_usuarios;
DROP PROCEDURE IF EXISTS sp_baja_unidad;
DROP PROCEDURE IF EXISTS sp_actualizar_unidad;
DROP PROCEDURE IF EXISTS sp_crear_unidad;
DROP PROCEDURE IF EXISTS sp_obtener_unidad;
DROP PROCEDURE IF EXISTS sp_listar_unidades;
DROP PROCEDURE IF EXISTS sp_eliminar_capacidad;
DROP PROCEDURE IF EXISTS sp_guardar_capacidad;
DROP PROCEDURE IF EXISTS sp_listar_capacidades;
DROP PROCEDURE IF EXISTS sp_actualizar_modelo;
DROP PROCEDURE IF EXISTS sp_crear_modelo;
DROP PROCEDURE IF EXISTS sp_obtener_modelo;
DROP PROCEDURE IF EXISTS sp_listar_modelos;
DROP PROCEDURE IF EXISTS sp_metricas_admin;
DROP PROCEDURE IF EXISTS sp_listar_auditoria;
DROP PROCEDURE IF EXISTS sp_registrar_auditoria;
DROP PROCEDURE IF EXISTS sp_obtener_historial_reciente;
DROP PROCEDURE IF EXISTS sp_version_esquema;
