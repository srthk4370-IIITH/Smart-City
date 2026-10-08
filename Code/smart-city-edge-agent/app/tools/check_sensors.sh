cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/device
rm -rf /tmp/sens && mkdir -p /tmp/sens && cp -r data web /tmp/sens/
./edge-agent-host --dir /tmp/sens --mock --addr 127.0.0.1:8093 --poll-ms 500 > /tmp/sens/log.txt 2>&1 &
sleep 2; head -2 /tmp/sens/log.txt
python3 /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/tools/check_sensors.py
kill %1
