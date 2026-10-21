-- ============================================================================
-- FTC Whisper — shared-auth migration
-- Run this ONCE in the FTC Contacts Supabase project
--   (ijeeghdxokfvlfarojlm) → Dashboard → SQL Editor → New query → Run.
--
-- Why: Whisper now authenticates against the SAME Supabase project as FTC
-- Contacts, so one login works in both apps. Contacts' project is missing the
-- two tables Whisper needs. This creates them (additive — nothing existing is
-- touched) with row-level security matching the old dedicated whisper project.
-- ============================================================================

-- ── app_settings ───────────────────────────────────────────────────────────
-- Shared, non-secret settings every signed-in user can read (window size,
-- dashboard defaults). Never a key: since 2026-10-05 a CHECK constraint refuses
-- credential-shaped rows, and AI refine goes through the BrightLink relay
-- (POST /api/whisper/ai), which keeps the model key on the server.
create table if not exists public.app_settings (
  key   text primary key,
  value text
);

alter table public.app_settings enable row level security;

drop policy if exists "app_settings read for authenticated" on public.app_settings;
create policy "app_settings read for authenticated"
  on public.app_settings for select
  to authenticated
  using (true);

-- ── transcriptions ─────────────────────────────────────────────────────────
-- Per-user dictation / refinement history. Each user sees only their own rows.
create table if not exists public.transcriptions (
  id               bigint generated always as identity primary key,
  user_id          uuid references auth.users(id) on delete cascade,
  transcribed_text text,
  refined_text     text,
  refinement_mode  text,
  app_name         text,
  app_exe          text,
  created_at       timestamptz not null default now()
);

-- Existing shared-project installs pre-date app attribution. Keep this
-- migration additive and idempotent so the script is safe to re-run.
alter table public.transcriptions
  add column if not exists app_name text,
  add column if not exists app_exe  text;

alter table public.transcriptions enable row level security;

drop policy if exists "transcriptions owner select" on public.transcriptions;
create policy "transcriptions owner select"
  on public.transcriptions for select
  to authenticated
  using (auth.uid() = user_id);

drop policy if exists "transcriptions owner insert" on public.transcriptions;
create policy "transcriptions owner insert"
  on public.transcriptions for insert
  to authenticated
  with check (auth.uid() = user_id);

drop policy if exists "transcriptions owner delete" on public.transcriptions;
create policy "transcriptions owner delete"
  on public.transcriptions for delete
  to authenticated
  using (auth.uid() = user_id);

create index if not exists transcriptions_user_created_idx
  on public.transcriptions (user_id, created_at desc);

-- AI keys never go in this table (2026-10-05): see the app_settings note above.
