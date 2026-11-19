-- =====================================================================
-- V002 · REVERSIÓN · Usuarios y acceso
-- Borra las tablas de V002 con sus datos (cuentas, sesiones y códigos).
-- Requiere haber revertido antes V003-V008, que dependen de usuarios.
-- =====================================================================

DROP TABLE IF EXISTS codigos_restablecimiento;

DROP TABLE IF EXISTS tokens_renovacion;

DROP TABLE IF EXISTS identidades_externas;

DROP TABLE IF EXISTS usuarios;
