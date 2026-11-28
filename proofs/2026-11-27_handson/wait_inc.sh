# block until an incident newer than INC-0012 exists (max 20 min)
for i in $(seq 1 240); do
  n=$(curl -s -m 5 127.0.0.1:8000/api/incidents | py -c "import json,sys;print(sum(1 for x in json.load(sys.stdin) if x['id']>'INC-0012'))" 2>/dev/null)
  [ "${n:-0}" -ge "${1:-1}" ] && { date +%T; exit 0; }
  timeout 5 tail -f /dev/null
done
