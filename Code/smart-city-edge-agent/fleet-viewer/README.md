# Fleet page (reports only)
Static page: sign in (Supabase email+password) -> boards, last health, open criticals, latest incidents and decisions, refresh 60 s.
Data is protected by RLS (anon = insert only, signed-in = read). supabase-js is vendored (dist/supabase.js), no CDN.

    sh make_config.sh            # writes dist/config.js from proofs/secrets/supabase.env (gitignored)
    wrangler pages deploy dist --project-name qidk-fleet --branch main
