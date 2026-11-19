#!/bin/bash
export PATH=$HOME/go-sdk/go/bin:/usr/bin:/bin
cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/backend
go vet . 2>&1 | head -40
