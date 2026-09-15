-- =============================================================================
-- Migration 007: Add catalogs table (Pieza 29 — Catalog closure)
-- =============================================================================
-- Hasta hoy el catálogo (30 ideas + aprobaciones/descartes del fundador)
-- vivía únicamente en cache/catalog/*.json sobre el disco efímero de Render
-- free tier: se borraba en cada deploy, expiraba a las 24h, y se invalidaba
-- si un solo carácter del brand_brain cambiaba. El fundador perdía el
-- catálogo que ya había pagado (15/25 créditos) y ya había aprobado.
--
-- Sigue el mismo patrón que brand_brains (ver supabase/schema.sql y
-- 001_add_user_auth_and_rls.sql): tabla con PK = session_token, jsonb para
-- el contenido variable, RLS activado SIN políticas (el backend accede con
-- la service key vía app/catalog/ideas.py, que la salta por diseño -- igual
-- que brand_brain/store.py).
-- =============================================================================

create table if not exists catalogs (
  session_token   text primary key references sessions(token) on delete cascade,
  niche           text,
  data            jsonb not null default '{}'::jsonb,
  catalog_locked  boolean not null default false,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- Index para debugging/monitoreo (mismo patrón que brand_brains_updated_at_idx)
create index if not exists catalogs_updated_at_idx on catalogs(updated_at);

-- Trigger para auto-actualizar updated_at -- reutiliza la función que ya
-- existe desde schema.sql (update_updated_at_column()), no se duplica.
drop trigger if exists update_catalogs_updated_at on catalogs;
create trigger update_catalogs_updated_at
  before update on catalogs
  for each row
  execute function update_updated_at_column();

-- RLS activado y sin políticas: acceso solo desde el backend con la service key.
alter table catalogs enable row level security;
