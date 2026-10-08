cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/device
rm -rf /tmp/rea && mkdir -p /tmp/rea && cp -r data web /tmp/rea/
./edge-agent-host --dir /tmp/rea --mock --addr 127.0.0.1:8096 --poll-ms 300 > /tmp/rea/log.txt 2>&1 &
sleep 2; python3 /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/tools/check_realert.py; kill %1
