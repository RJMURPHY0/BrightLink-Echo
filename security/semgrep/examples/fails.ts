// Each line here should be flagged by security/semgrep/brightlink.yml.
export const a = (x: string) => x === process.env.CRON_SECRET;
export const b = (x: string) => process.env.AUTO_FIX_SECRET !== x;
export const c = import.meta.env.VITE_STRIPE_SECRET_KEY;
