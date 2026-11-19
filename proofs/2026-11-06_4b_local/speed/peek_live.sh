#!/usr/bin/env bash
grep -E "shared prefix|OOM|step [0-9]+/|fit levers|Error" ~/smartcity_runs/rsn3_4b_r3/train.log | tail -6
