cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/device
rm -rf /tmp/orc && mkdir -p /tmp/orc && cp -r data web /tmp/orc/
./edge-agent-host --dir /tmp/orc --mock --addr 127.0.0.1:8092 --poll-ms 100 > /tmp/orc/log.txt 2>&1 &
sleep 3
python3 /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/tools/check_orchestrator.py
kill %1
