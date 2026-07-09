#!/bin/bash
cd ~/site-agent
nohup .venv/bin/python -m src.main \
  --input data/full_tam_run.csv \
  --orgs data/output_orgs.csv \
  --locations data/output_locations.csv \
  --limit 2000 \
  --concurrency 30 \
  --max-cost 300 \
  > data/chunk1.log 2>&1 &
echo "PID: $!"
