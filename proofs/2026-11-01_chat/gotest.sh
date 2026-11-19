#!/bin/bash
export PATH=$HOME/go-sdk/go/bin:$PATH
cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/backend
go vet ./... && go test -count=${2:-1} ${1:+-run "$1"} ./... 2>&1 | tail -40
