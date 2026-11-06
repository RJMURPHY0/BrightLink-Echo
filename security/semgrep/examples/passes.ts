// Nothing here should be flagged.
import { safeCompare } from "./safe";
export const a = (x: string) => safeCompare(x, process.env.CRON_SECRET);
export const b = process.env.NODE_ENV === "production";
export const c = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
