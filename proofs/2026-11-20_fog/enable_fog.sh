#!/bin/sh
# NOT RUN. Adds supabase_url/supabase_key to htpd_profile on the board. Run on the laptop with the app STOPPED.
# Reads proofs/secrets/supabase.env at runtime; the key is never echoed.
set -e
. "$(dirname "$0")/../secrets/supabase.env"
W=/data/local/tmp/smart_city_edge
T=$(mktemp); trap 'rm -f "$T"' EXIT
adb pull $W/htpd_profile "$T" 2>/dev/null || : > "$T"
grep -v '^supabase_' "$T" > "$T.n" || true
{ cat "$T.n"; echo "supabase_url=$SUPABASE_URL"; echo "supabase_key=$SUPABASE_ANON_KEY"; } > "$T.f"
adb push "$T.f" $W/htpd_profile.part >/dev/null
adb shell "mv $W/htpd_profile.part $W/htpd_profile"
rm -f "$T.n" "$T.f"
echo "fog enabled in htpd_profile (restart the app)"
