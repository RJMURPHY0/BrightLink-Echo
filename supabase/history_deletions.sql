-- Echo history deletions: server-side tombstones so a dictation deleted on one
-- PC stays deleted on every PC (RJMURPHY0/BrightLink-Echo issue #2).
--
-- Before this, Echo recorded deletes only in each PC's history-tombstones.json.
-- Another PC with Cloud Sync on saw a local row the cloud lacked and uploaded
-- it again; once the deleting PC's 30-day purge dropped its local stone it
-- downloaded the row back. Clear-history cutoffs and synced recordings had the
-- same hole. That defeats the user's erasure (UK GDPR Article 17).
--
-- Now:
--   1. echo_history_deletions  one row per delete (kind 'row') or clear
--                              (kind 'before', a cutoff). Holds no words: the
--                              row's time, a SHA-256 of its text (pseudonymous:
--                              a short common phrase is guessable from it) and
--                              the recording key. Owner can read and add, never
--                              change or remove; account deletion cascades.
--   2. echo_history_delete     RPC: records stones and deletes the matching
--                              transcriptions rows in one transaction.
--   3. echo_history_deletions_page  keyset page of the caller's stones, so
--                              other PCs erase their local copies.
--   4. transcriptions_block_deleted  BEFORE INSERT: a row matching a stone is
--                              silently skipped. Installed old Echo versions
--                              keep re-uploading the old way; their insert
--                              "succeeds" with no row, and the rest of their
--                              batch still lands.
--   5. echo-sync-audio insert/update policies refuse a deleted recording's
--                              key. Select/delete unchanged so a client can
--                              still list and remove it (SQL cannot delete
--                              storage objects: storage.protect_delete).
--
-- Match rule (mirrored in Echo's supabase_client.py, keep the two in step):
-- a transcription is deleted when a 'before' stone's time is >= its
-- created_at, or a 'row' stone has exactly its created_at (Retry
-- transcription rewrites the text, never the time), or a 'row' stone is
-- within 10 s with the same text hash (builds before v1.8 minted separate
-- local and remote timestamps).
--
-- Known limits: a PC whose clock runs behind can have a dictation made just
-- after another PC's Clear treated as cleared (Echo stamps created_at on the
-- client); two identical dictations within 10 s count as one.
--
-- Additive and idempotent. Only Echo writes transcriptions; Brightlink's
-- activity feed only reads it.

-- ── 1. echo_history_deletions ───────────────────────────────────────────────

create table if not exists public.echo_history_deletions (
  id           bigint generated always as identity primary key,
  user_id      uuid not null default auth.uid() references auth.users(id) on delete cascade,
  kind         text not null check (kind in ('row', 'before')),
  created_at   timestamptz not null,
  text_sha256  text check (text_sha256 is null or text_sha256 ~ '^[0-9a-f]{64}$'),
  audio_key    text not null default '',
  deleted_at   timestamptz not null default now(),
  check (kind = 'row' or text_sha256 is null)
);

comment on table public.echo_history_deletions is
  'BrightLink Echo: dictations the user deleted (kind row) or cleared (kind before, a cutoff). No words: time, SHA-256 of the text, recording key. Every PC hides and erases matching history; inserts into transcriptions and echo-sync-audio uploads that match are refused. Owner reads and adds only.';

create unique index if not exists echo_history_deletions_identity
  on public.echo_history_deletions (user_id, kind, created_at, coalesce(text_sha256, ''));
create index if not exists echo_history_deletions_user_id
  on public.echo_history_deletions (user_id, id);
create index if not exists echo_history_deletions_user_audio
  on public.echo_history_deletions (user_id, audio_key collate "C");

-- Server-computed fields: a client can never shift a cutoff into the future,
-- smuggle words into the hash column, or mislabel the recording key.
create or replace function public.echo_history_deletions_normalise()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.kind = 'before' then
    new.created_at := least(new.created_at, now());
    new.text_sha256 := null;
  else
    new.text_sha256 := lower(nullif(new.text_sha256, ''));
  end if;
  -- Same as audio_store.canonical_key: UTC YYYYMMDDHHMMSSffffff.
  new.audio_key := to_char(new.created_at at time zone 'UTC', 'YYYYMMDDHH24MISSUS');
  new.deleted_at := now();
  return new;
end
$$;

revoke all on function public.echo_history_deletions_normalise() from public, anon, authenticated;

drop trigger if exists echo_history_deletions_normalise on public.echo_history_deletions;
create trigger echo_history_deletions_normalise
  before insert on public.echo_history_deletions
  for each row execute function public.echo_history_deletions_normalise();

alter table public.echo_history_deletions enable row level security;

revoke all on table public.echo_history_deletions from anon, authenticated;
grant select, insert on table public.echo_history_deletions to authenticated;

drop policy if exists "echo_history_deletions select own" on public.echo_history_deletions;
create policy "echo_history_deletions select own" on public.echo_history_deletions
  for select to authenticated
  using (user_id = (select auth.uid()));

drop policy if exists "echo_history_deletions insert own" on public.echo_history_deletions;
create policy "echo_history_deletions insert own" on public.echo_history_deletions
  for insert to authenticated
  with check (user_id = (select auth.uid()));

-- ── 2. Match rule (internal) ────────────────────────────────────────────────

create or replace function public.echo_history_row_deleted(
  p_user uuid, p_created timestamptz, p_text text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select p_user is not null and p_created is not null and (
    exists (
      select 1 from public.echo_history_deletions d
      where d.user_id = p_user
        and d.kind = 'before'
        and d.created_at >= p_created
    )
    or exists (
      select 1 from public.echo_history_deletions d
      where d.user_id = p_user
        and d.kind = 'row'
        and d.created_at between p_created - interval '10 seconds'
                             and p_created + interval '10 seconds'
        and (d.created_at = p_created
             or d.text_sha256 = encode(sha256(convert_to(coalesce(p_text, ''), 'UTF8')), 'hex'))
    )
  );
$$;

revoke all on function public.echo_history_row_deleted(uuid, timestamptz, text) from public, anon, authenticated;

-- ── 3. RPC: delete ──────────────────────────────────────────────────────────

create or replace function public.echo_history_delete(
  p_rows jsonb default '[]'::jsonb,
  p_before timestamptz default null)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_uid uuid := (select auth.uid());
  v_rows jsonb := coalesce(p_rows, '[]'::jsonb);
  v_cutoff timestamptz := least(p_before, now());
  v_n int;
  v_stones int := 0;
  v_deleted int := 0;
begin
  if v_uid is null then
    raise exception 'not signed in' using errcode = '42501';
  end if;
  if jsonb_typeof(v_rows) <> 'array' then
    raise exception 'p_rows must be a JSON array' using errcode = '22023';
  end if;
  if jsonb_array_length(v_rows) > 500 then
    raise exception 'at most 500 rows per call' using errcode = '22023';
  end if;

  if p_before is not null then
    insert into public.echo_history_deletions (user_id, kind, created_at)
    values (v_uid, 'before', v_cutoff)
    on conflict do nothing;
    get diagnostics v_n = row_count;
    v_stones := v_stones + v_n;

    delete from public.transcriptions t
    where t.user_id = v_uid and t.created_at <= v_cutoff;
    get diagnostics v_n = row_count;
    v_deleted := v_deleted + v_n;
  end if;

  if jsonb_array_length(v_rows) > 0 then
    -- A malformed hash is dropped rather than failing the batch: the exact
    -- time still matches, and one bad element must not block the rest.
    insert into public.echo_history_deletions (user_id, kind, created_at, text_sha256)
    select v_uid, 'row', r.created_at,
           case when r.text_sha256 ~ '^[0-9a-fA-F]{64}$' then lower(r.text_sha256) end
    from jsonb_to_recordset(v_rows) as r(created_at timestamptz, text_sha256 text)
    where r.created_at between timestamptz '2000-01-01' and now() + interval '1 day'
    on conflict do nothing;
    get diagnostics v_n = row_count;
    v_stones := v_stones + v_n;

    delete from public.transcriptions t
    using (
      select r.created_at,
             case when r.text_sha256 ~ '^[0-9a-fA-F]{64}$' then lower(r.text_sha256) end as text_sha256
      from jsonb_to_recordset(v_rows) as r(created_at timestamptz, text_sha256 text)
      where r.created_at between timestamptz '2000-01-01' and now() + interval '1 day'
    ) s
    where t.user_id = v_uid
      and t.created_at between s.created_at - interval '10 seconds'
                           and s.created_at + interval '10 seconds'
      and (t.created_at = s.created_at
           or s.text_sha256 = encode(sha256(convert_to(coalesce(t.transcribed_text, ''), 'UTF8')), 'hex'));
    get diagnostics v_n = row_count;
    v_deleted := v_deleted + v_n;
  end if;

  return jsonb_build_object('stones', v_stones, 'rows_deleted', v_deleted);
end
$$;

revoke all on function public.echo_history_delete(jsonb, timestamptz) from public, anon;
grant execute on function public.echo_history_delete(jsonb, timestamptz) to authenticated;

-- ── 4. RPC: keyset page of the caller's stones ──────────────────────────────

create or replace function public.echo_history_deletions_page(
  p_after_id bigint default 0,
  p_limit int default 500)
returns table (id bigint, kind text, created_at timestamptz,
               text_sha256 text, audio_key text, deleted_at timestamptz)
language sql
stable
security invoker
set search_path = ''
as $$
  select d.id, d.kind, d.created_at, d.text_sha256, d.audio_key, d.deleted_at
  from public.echo_history_deletions d
  where d.user_id = (select auth.uid())
    and d.id > coalesce(p_after_id, 0)
  order by d.id
  limit least(greatest(coalesce(p_limit, 500), 1), 500);
$$;

revoke all on function public.echo_history_deletions_page(bigint, int) from public, anon;
grant execute on function public.echo_history_deletions_page(bigint, int) to authenticated;

-- ── 5. transcriptions: refuse deleted rows ──────────────────────────────────
-- Named so it sorts before transcriptions_stamp_org (same-event BEFORE
-- triggers fire alphabetically): no point stamping a row that is dropped.

create or replace function public.echo_transcriptions_block_deleted()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if public.echo_history_row_deleted(new.user_id, new.created_at, new.transcribed_text) then
    return null;
  end if;
  return new;
end
$$;

revoke all on function public.echo_transcriptions_block_deleted() from public, anon, authenticated;

do $$
begin
  if to_regclass('public.transcriptions') is not null then
    execute 'drop trigger if exists transcriptions_block_deleted on public.transcriptions';
    execute 'create trigger transcriptions_block_deleted
               before insert on public.transcriptions
               for each row execute function public.echo_transcriptions_block_deleted()';
  end if;
end
$$;

-- ── 6. echo-sync-audio: refuse a deleted recording ──────────────────────────
-- Invoker rights: it reads the caller's own stones through their own select
-- policy, and auth.uid() is inside, never a parameter.

create or replace function public.echo_sync_audio_deleted(p_name text)
returns boolean
language sql
stable
security invoker
set search_path = ''
as $$
  with k as (
    select regexp_replace(split_part(coalesce(p_name, ''), '/', 2), '\.wav$', '') as key
  )
  select exists (
    select 1
    from public.echo_history_deletions d, k
    where d.user_id = (select auth.uid())
      and split_part(coalesce(p_name, ''), '/', 1) = (select auth.uid())::text
      and (
        (d.kind = 'row' and d.audio_key collate "C" = k.key collate "C")
        or (d.kind = 'before' and k.key ~ '^[0-9]{20}$'
            and d.audio_key collate "C" >= k.key collate "C")
      )
  );
$$;

revoke all on function public.echo_sync_audio_deleted(text) from public, anon;
grant execute on function public.echo_sync_audio_deleted(text) to authenticated;

drop policy if exists "echo_sync_audio insert own" on storage.objects;
create policy "echo_sync_audio insert own" on storage.objects
  for insert to authenticated
  with check (
    bucket_id = 'echo-sync-audio'
    and (storage.foldername(name))[1] = (select auth.uid())::text
    and not public.echo_sync_audio_deleted(name)
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
    and not public.echo_sync_audio_deleted(name)
  );
