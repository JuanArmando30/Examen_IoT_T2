-- =====================================================================
-- V016 · Accesorios (LUZ, SONIDO, ENCENDER/APAGAR) también para INVITADOS
--
-- Antes: V001 sembró las capacidades de tipo 'accesorio' con
-- permitido_invitado = 0, así que sp_comandos_invitado no las devolvía y la
-- página de Control del invitado no mostraba los botones de luz, sonido ni
-- encendido (administrador y cliente sí los ven).
--
-- Ahora: todas las capacidades de tipo 'accesorio' quedan permitidas a
-- invitados. La empresa puede volver a quitarlas por modelo en
-- Administración › Modelos › Capacidades («Permitido a invitados»), y
-- bloquear el comando en una unidad sigue impidiendo su uso a todos.
-- Las reservas en curso lo reflejan en la siguiente reserva/recarga.
-- Sin cambios de tablas. Reversión: V016__accesorios_invitado.down.sql.
-- =====================================================================

-- @previo existe columna modelo_comandos.permitido_invitado

UPDATE modelo_comandos
   SET permitido_invitado = 1
 WHERE tipo = 'accesorio' AND permitido_invitado = 0;

DELIMITER $$

DROP PROCEDURE IF EXISTS sp_version_esquema$$
CREATE PROCEDURE sp_version_esquema()
BEGIN
  SELECT 16 AS version;
END$$

DELIMITER ;

-- @verificar SELECT COUNT(*) = 0 FROM modelo_comandos WHERE tipo = 'accesorio' AND permitido_invitado = 0
-- @verificar SELECT COUNT(*) = 0 FROM modelo_comandos WHERE tipo = 'paro' AND permitido_invitado = 0
