-- Echo Cloud Sync: opt-in (default OFF) sync of everything personal in the
-- BrightLink Echo desktop app between a user's PCs. The app is a separate
-- Python repo (RJMURPHY0/BrightLink-Echo, cloud_sync.py); this is the database
-- side, applied here because this repo owns migrations for the shared project.
--
-- What already existed and is reused unchanged: transcriptions (history text),
-- user_vocabulary / user_snippets (already "for all" own-row RLS, so delete
-- works), user_daily_stats (usage counts; stays outside Cloud Sync because
-- BrightLink Home reads it).
--
-- New here:
--   1. echo_user_state   one jsonb row per (user, key): "settings" (synced
--                        preferences with per-setting change times) and
--                        "phrases" (learned-phrase counts).
--   2. echo-sync-audio   private bucket, "<user_id>/<timestamp>.wav" per
--                        dictation, owner-only.
--   3. transcriptions    owner UPDATE (History "Retry transcription" rewrites
--                        a row) and owner DELETE (Settings "Delete my data
--                        from the cloud"), added only if the table exists.
--
-- Additive and idempotent. Touches nothing another product writes; the
-- activity feed (sa_product_rows) only reads transcriptions and is unaffected.

-- ── 1. echo_user_state ──────────────────────────────────────────────────────

create table if not exists public.echo_user_state (
  user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
  key         text not null check (key in ('settings', 'phrases')),
  data        jsonb not null default '{}'::jsonb,
  updated_at  timestamptz not null default now(),
  primary key (user_id, key)
);

comment on table public.echo_user_state is
  'BrightLink Echo Cloud Sync (opt-in): the user''s synced preferences ("settings") and learned phrases ("phrases") as one jsonb row each, merged by the desktop app. Owner-only.';

alter table public.echo_user_state enable row level security;

drop policy if exists "echo_user_state own" on public.echo_user_state;
create policy "echo_user_state own" on public.echo_user_state
  for all to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

-- ── 2. echo-sync-audio bucket ───────────────────────────────────────────────
-- Same foldername-scoped ownership as echo-feedback-audio and crm-files, but
-- the owner can read and delete their own recordings (that is the point:
-- another of their PCs plays them back), and nobody else can, including the
-- super admin.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('echo-sync-audio', 'echo-sync-audio', false, 26214400, array['audio/wav', 'audio/x-wav'])
on conflict (id) do nothing;

drop policy if exists "echo_sync_audio select own" on storage.objects;
create policy "echo_sync_audio select own" on storage.objects
  for select to authenticated
  using (
    bucket_id = 'echo-sync-audio'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

drop policy if exists "echo_sync_audio insert own" on storage.objects;
create policy "echo_sync_audio insert own" on storage.objects
  for insert to authenticated
  with check (
    bucket_id = 'echo-sync-audio'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

drop policy if exists "echo_sync_audio update own" on storage.objects;
create policy "echo_sync_audio update own" on storage.objects
  for update to authenticated
  using (
    bucket_id = 'echo-sync-audio'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  )
  with check (
    bucket_id = 'echo-sync-audio'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

drop policy if exists "echo_sync_audio delete own" on storage.objects;
create policy "echo_sync_audio delete own" on storage.objects
  for delete to authenticated
  using (
    bucket_id = 'echo-sync-audio'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

-- ── 3. transcriptions owner update / delete ─────────────────────────────────
-- Permissive policies OR together, so adding these cannot narrow anything
-- that already works. Guarded: the table belongs to the desktop app.

do $$
begin
  if to_regclass('public.transcriptions') is not null then
    execute 'drop policy if exists "echo_transcriptions update own" on public.transcriptions';
    execute 'create policy "echo_transcriptions update own" on public.transcriptions
               for update to authenticated
               using (user_id = (select auth.uid()))
               with check (user_id = (select auth.uid()))';
    execute 'drop policy if exists "echo_transcriptions delete own" on public.transcriptions';
    execute 'create policy "echo_transcriptions delete own" on public.transcriptions
               for delete to authenticated
               using (user_id = (select auth.uid()))';
  end if;
end
$$;
