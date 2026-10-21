#!/bin/sh
set -eu

# A named volume or bind mount can hide the ownership prepared at image build
# time. Prepare the complete persistent tree while still running as root.
mkdir -p /data/uploads/photos /data/uploads/thumbs
chown -R app:app /data

exec gosu app "$@"
