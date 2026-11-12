-- error_events retention: 90 days (PRIVACY.md, "Diagnostics").
--
-- error_events is Echo's fleet fault log (mic, insert, press and stop timing,
-- crash reports). It had no purge and kept every row from 28 Jul 2026. The
-- published policy now says reports are deleted after 90 days, so this job
-- deletes them daily, the same way error-logs-purge keeps public.error_logs.
-- created_at is indexed (error_events_created_at_idx), so the delete is a
-- range scan. cron.schedule with an existing name updates that job, so this
-- file can be re-run.
--
-- Shared project ijeeghdxokfvlfarojlm, applied live as migration
-- error_events_retention on 12 Nov 2026 (db-reviewer PASS, db-copy PASS).
-- Rollback: select cron.unschedule('error-events-purge');

select cron.schedule(
  'error-events-purge',
  '29 3 * * *',
  $$delete from public.error_events where created_at < now() - interval '90 days'$$
);
