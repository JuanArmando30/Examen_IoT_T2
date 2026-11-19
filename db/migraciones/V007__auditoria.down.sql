-- =====================================================================
-- V007 · REVERSIÓN · Auditoría
-- Borra la bitácora con sus registros. Solo para la copia de prueba: en
-- producción la auditoría es evidencia y no debería revertirse.
-- =====================================================================

DROP TABLE IF EXISTS auditoria;
