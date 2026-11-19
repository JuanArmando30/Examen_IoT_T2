-- =====================================================================
-- V004 · REVERSIÓN · DEMO de fábrica y privadas
-- Quita las columnas nuevas de demos. Las DEMO privadas, si existieran,
-- quedarían como DEMO normales de su unidad (no se borran).
-- =====================================================================

-- @si existe fk demos.fk_demo_propietario
ALTER TABLE demos DROP FOREIGN KEY fk_demo_propietario;

-- @si existe check demos.ck_demo_ambito
ALTER TABLE demos DROP CHECK ck_demo_ambito;

-- @si existe indice demos.fk_demo_propietario
ALTER TABLE demos DROP INDEX fk_demo_propietario;

-- @si existe columna demos.id_propietario
ALTER TABLE demos DROP COLUMN id_propietario;

-- @si existe columna demos.ambito
ALTER TABLE demos DROP COLUMN ambito;
