cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/device
rm -rf /tmp/bat && mkdir -p /tmp/bat && cp -r data web /tmp/bat/
./edge-agent-host --dir /tmp/bat --mock --addr 127.0.0.1:8094 --poll-ms 400 > /tmp/bat/log.txt 2>&1 &
sleep 2; python3 /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/tools/check_batch.py; kill %1
