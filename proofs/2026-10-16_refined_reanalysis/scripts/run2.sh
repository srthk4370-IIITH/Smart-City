R=/mnt/c/Users/hp/AppData/Local/Temp/claude/C--Users-hp-Desktop-qidk/125df7ac-c9eb-46de-b63b-ce87f4c7e8ce/scratchpad/run2
D=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/device
rm -rf $R; mkdir -p $R/state
ln -s $D/data $R/data
ln -s $D/web $R/web
cp $D/edge-agent-host /tmp/edge-host2 && chmod +x /tmp/edge-host2
cd $R && exec /tmp/edge-host2 -mock -dir $R -addr 0.0.0.0:8766 -genie /nonexistent -poll-ms 2000 > $R/backend.log 2>&1
