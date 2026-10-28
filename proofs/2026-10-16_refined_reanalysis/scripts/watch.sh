for i in $(seq 1 90); do
  T=$(date +%H:%M:%S)
  S=$(curl -s localhost:8766/api/status | grep -o '"sim_time_ist":"[^"]*"')
  L=$(curl -s localhost:8766/api/incidents | grep -o '"id":"INC-0001"\|"refine_stage":"[^"]*"\|"next_refine_sim":[0-9]*\|"severity":"[^"]*"\|"state":"[^"]*"\|"revisions":[0-9]*' | tr '\n' ' ')
  echo "$T $S $L"
  sleep 2
done
