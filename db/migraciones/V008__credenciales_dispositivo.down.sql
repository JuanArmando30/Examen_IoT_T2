-- =====================================================================
-- V008 · REVERSIÓN · Credenciales de dispositivo
-- Borra la tabla. Si el firmware ya usara credenciales, se desconectaría:
-- revertir solo en la copia o antes de actualizar el firmware.
-- =====================================================================

DROP TABLE IF EXISTS credenciales_dispositivo;
