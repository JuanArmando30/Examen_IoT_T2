-- =====================================================================
-- V004 · DEMO de fábrica (empresa) y DEMO privadas (de un comprador)
-- Proyecto ADMINISTRACIÓN · Etapa 2
--
-- demos.ambito: 'fabrica' (las crea la empresa) o 'privada' (las crea un
--   comprador para SU unidad). Las 2 DEMO actuales quedan como 'fabrica'
--   por el DEFAULT; no se mueven ni cambian de ID.
-- demos.id_propietario: dueño de una DEMO privada (NULL en las de fábrica).
-- La regla «privada <=> tiene propietario» la aplican los SP y el servicio:
--   MySQL no admite CHECK sobre columnas con llaves foráneas que tienen
--   acciones referenciales, y conviene no depender de ese caso límite.
-- sp_crear_demo y sp_obtener_demos siguen funcionando igual.
-- Reversión: V004__demos_de_fabrica_y_privadas.down.sql
-- =====================================================================

-- @previo existe tabla demos
-- @previo existe tabla usuarios
-- @previo no-existe columna demos.ambito
-- @previo no-existe columna demos.id_propietario

ALTER TABLE demos
  ADD COLUMN ambito         VARCHAR(8) NOT NULL DEFAULT 'fabrica' AFTER id_vehiculo,
  ADD COLUMN id_propietario INT        DEFAULT NULL AFTER ambito,
  ADD KEY fk_demo_propietario (id_propietario),
  ADD CONSTRAINT fk_demo_propietario FOREIGN KEY (id_propietario)
    REFERENCES usuarios (id_usuario) ON DELETE RESTRICT ON UPDATE RESTRICT,
  ADD CONSTRAINT ck_demo_ambito CHECK (ambito IN ('fabrica', 'privada'));

-- @verificar SELECT COUNT(*) = 0 FROM demos WHERE ambito <> 'fabrica' OR id_propietario IS NOT NULL
