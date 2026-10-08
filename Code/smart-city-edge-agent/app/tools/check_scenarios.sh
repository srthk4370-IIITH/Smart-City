cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/device
pkill -f "edge-agent-host.*8091" 2>/dev/null; rm -rf /tmp/scn && mkdir -p /tmp/scn && cp -r data web /tmp/scn/ 2>/dev/null
./edge-agent-host --dir /tmp/scn --mock --addr 127.0.0.1:8091 --poll-ms 100 > /tmp/scn/log.txt 2>&1 &
sleep 3
python3 /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/tools/check_scenarios.py
kill %1
