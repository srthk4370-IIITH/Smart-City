#!/bin/bash
# helper: run a python file with the rsn venv from /tmp
cd /tmp && exec nice ~/venvs/rsn/bin/python "$@"
