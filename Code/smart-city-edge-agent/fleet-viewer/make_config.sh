#!/bin/sh
# writes dist/config.js from the gitignored secrets file (publishable key; protected by RLS). Never commit config.js.
set -e
D=$(dirname "$0"); E="$D/../../../proofs/secrets/supabase.env"
. "$E"
printf 'var FLEET_CONFIG={url:"%s",key:"%s"};\n' "$SUPABASE_URL" "$SUPABASE_ANON_KEY" > "$D/dist/config.js"
