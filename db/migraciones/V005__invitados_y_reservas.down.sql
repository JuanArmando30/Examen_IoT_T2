-- =====================================================================
-- V005 · REVERSIÓN · Sesiones de invitado y reservas de exhibición
-- Requiere haber revertido antes V006 (historial apunta a sesiones_invitado).
-- =====================================================================

DROP TABLE IF EXISTS reservas_exhibicion;

DROP TABLE IF EXISTS sesiones_invitado;
