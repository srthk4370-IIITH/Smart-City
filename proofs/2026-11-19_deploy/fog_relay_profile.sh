#!/bin/bash
# board has no internet: Supabase rows go via the laptop relay (127.0.0.1:8095 -> HTTPS)
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
P=/data/local/tmp/smart_city_edge/htpd_profile
stop_app >/dev/null
sh_ "sed -i 's#^supabase_url=.*#supabase_url=http://127.0.0.1:8095#' $P; grep -c '^supabase_url=http://127.0.0.1:8095' $P"
start_app >/dev/null && echo APP_UP
