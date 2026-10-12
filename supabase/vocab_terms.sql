-- Echo vocabulary from the people and companies the user actually deals with.
--
-- Echo corrects and capitalises names using a "managed" vocabulary built from
-- the CRM. It used to take the first 150 contacts rows the user could see,
-- which for a team with scraped lead lists meant US forklift dealers with full
-- postal addresses, and none of the names they dictate (term_bench,
-- 2026-10-12). This ranks contacts by the user's own recent two-way contact
-- with them and adds their colleagues' names. Echo caches the list locally.
--
-- What counts: mail received from them, emails the user sent by hand (sequence
-- sends barely count: they go to cold leads), calls, meetings and demos,
-- LinkedIn conversations, notes, and deals the user created or owns. Each event
-- decays with a 45-day time constant over the last 180 days; a timestamp in
-- the future counts as now. contact_activities rows of type 'email' are
-- mirrors of email_sends and automated LinkedIn touches are not contact, so
-- neither is counted.
--
-- Security invoker: every table is read through the caller's own RLS, so a
-- user only gets names they can already see. Colleagues come from
-- get_org_team_members(), the Team page's own roster (org_members RLS shows a
-- member only their own row). Read-only, idempotent.
--
-- rollback: drop function public.echo_vocab_terms(int);

create or replace function public.echo_vocab_terms(p_limit int default 150)
returns table (term text, kind text, score real)
language sql
stable
security invoker
set search_path = ''
as $$
  with ev as (
    select m.contact_id, m.received_at as at, 1.0::float8 as w
      from public.mailbox_messages m
     where m.user_id = (select auth.uid()) and m.contact_id is not null
       and m.received_at > now() - interval '180 days'
    union all
    select e.contact_id, e.sent_at, case when e.sequence_id is null then 3.0 else 0.2 end
      from public.email_sends e
     where e.user_id = (select auth.uid()) and e.contact_id is not null
       and e.status is distinct from 'bounced'
       and e.sent_at > now() - interval '180 days'
    union all
    select a.contact_id, a.created_at,
           case a.type when 'meeting' then 4.0 when 'demo' then 4.0
                       when 'call' then 3.0 else 2.0 end
      from public.contact_activities a
     where a.user_id = (select auth.uid()) and a.contact_id is not null
       and a.type in ('meeting', 'demo', 'call', 'linkedin_dm')
       and a.created_at > now() - interval '180 days'
    union all
    select n.contact_id, n.created_at, 2.0
      from public.contact_notes n
     where n.user_id = (select auth.uid()) and n.contact_id is not null
       and n.created_at > now() - interval '180 days'
    union all
    select c.contact_id, c.created_at, 3.0
      from public.call_records c
     where c.user_id = (select auth.uid()) and c.contact_id is not null
       and c.created_at > now() - interval '180 days'
    union all
    -- deals.owner_id is a team_members id, not an auth user id.
    select d.contact_id, coalesce(d.updated_at, d.created_at), 4.0
      from public.deals d
     where (d.user_id = (select auth.uid())
            or d.owner_id in (select public.my_team_member_ids()))
       and d.contact_id is not null
       and d.status is distinct from 'lost'
       and coalesce(d.updated_at, d.created_at) > now() - interval '180 days'
    union all
    select l.contact_id, coalesce(l.last_message_at, l.created_at), 2.0
      from public.linkedin_chats l
     where l.user_id = (select auth.uid()) and l.contact_id is not null
       and coalesce(l.last_message_at, l.created_at) > now() - interval '180 days'
  ),
  scored as (
    select contact_id,
           sum(w * exp(-greatest(extract(epoch from (now() - at)), 0)
                       / 86400.0 / 45.0)) as s
      from ev
     where at is not null
     group by contact_id
  ),
  raw as (
    select trim(concat_ws(' ', nullif(trim(c.first_name), ''),
                               nullif(trim(c.last_name), ''))) as term,
           'person'::text as kind, sc.s
      from scored sc join public.contacts c on c.id = sc.contact_id
    union all
    select trim(c.company), 'company', sc.s
      from scored sc join public.contacts c on c.id = sc.contact_id
     where nullif(trim(c.company), '') is not null
    union all
    -- Colleagues: dictated constantly, rarely contacts. Capped so a large
    -- team cannot crowd out every customer.
    -- A display name left as an email's local part ("lee.brookes") becomes
    -- "Lee Brookes": the dotted form would re-case nothing useful.
    select * from (
      select case when trim(t.name) ~ '^[A-Za-z]+[._][A-Za-z]+$'
                  then initcap(regexp_replace(trim(t.name), '[._]', ' '))
                  else trim(t.name) end,
             'colleague', 30.0::float8
        from public.get_org_team_members() t
       where t.user_id is distinct from (select auth.uid())
         and nullif(trim(t.name), '') is not null
       order by t.name
       limit 40
    ) team
  ),
  usable as (
    select term, kind, s
      from raw
     where length(term) between 3 and 80
       -- A first name alone ("Will", "Mark") would re-case ordinary words.
       and (kind <> 'person' or term ~ '\S\s+\S')
       -- Emails, paths and addresses or phone numbers are not names.
       and term !~ '[@/]' and term !~ '[0-9]{3,}'
       and lower(term) not in ('private', 'self-employed', 'self employed',
                               'freelance', 'freelancer', 'retired', 'student',
                               'n/a', 'na', 'none', 'unknown', 'other', 'test',
                               'individual', 'personal')
  ),
  per_spelling as (
    select term,
           case when bool_or(kind = 'colleague') then 'colleague'
                when bool_or(kind = 'person') then 'person'
                else 'company' end as kind,
           count(*) as n,
           sum(s) as s
      from usable
     group by term
  ),
  spelled as (
    -- One row per name, case-insensitively. Echo also re-cases text to these
    -- spellings, so: never all lower case, never a SHOUTED multi-word name
    -- ("FTC SAFETY SOLUTIONS"), then the most capitals ("FTC Safety
    -- Solutions" over "Ftc Safety Solutions", a lone "DHL" over "Dhl"), then
    -- the most common. The activity behind every spelling sums, and the kind
    -- comes from the whole group.
    select term,
           case when bool_or(kind = 'colleague') over w then 'colleague'
                when bool_or(kind = 'person') over w then 'person'
                else 'company' end as kind,
           sum(s) over w as total,
           row_number() over (
             partition by lower(term)
             order by (term = lower(term)),
                      (term = upper(term) and term ~ ' '),
                      length(regexp_replace(term, '[^A-Z]', '', 'g')) desc,
                      n desc,
                      term) as rn
      from per_spelling
    window w as (partition by lower(term))
  )
  select term, kind, total::real
    from spelled
   where rn = 1
   order by total desc, term
   limit least(greatest(coalesce(p_limit, 150), 1), 300);
$$;

revoke all on function public.echo_vocab_terms(int) from public, anon, authenticated;
grant execute on function public.echo_vocab_terms(int) to authenticated;

comment on function public.echo_vocab_terms(int) is
  'BrightLink Echo: the caller''s most relevant names (contacts and companies ranked by their own recent two-way activity, plus colleagues) for dictation vocabulary. Security invoker, read-only.';
