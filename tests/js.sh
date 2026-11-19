#!/bin/sh
exec "${PYTHON:-python3}" "$(dirname "$0")/run.py" --backend js "$@"
