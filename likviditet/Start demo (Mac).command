#!/bin/bash
# Starter likviditetsappen med fiktive demodata. Dobbeltklik for at starte.
cd "$(dirname "$0")" && DATA_DIR="$PWD/data-demo" DEMO=1 bash scripts/start-mac.sh
