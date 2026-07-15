#!/bin/bash
# Two-phase comparison, one stack at a time (for resource-constrained machines):
#   1. Bring up the scalable stack -> load test -> capture -> tear down
#   2. Bring up the monolith        -> load test -> capture -> tear down
#   3. Generate the comparison table from both result files
set -e

cd "$(dirname "$0")/.."   # project root

DURATION=${1:-20}
CONCURRENCY=${2:-40}

echo "=================================================="
echo "PHASE 1: Scalable architecture (3 workers + replica + Redis)"
echo "=================================================="
docker compose up -d --build
echo "Waiting for the stack to settle (replica clone, health checks)..."
sleep 15

python3 tools/load_test.py --url http://localhost:8080 --label scalable \
    --duration "$DURATION" --concurrency "$CONCURRENCY" --out results_scalable.json

echo "Tearing down scalable stack..."
docker compose down -v

echo ""
echo "=================================================="
echo "PHASE 2: Monolith"
echo "=================================================="
docker compose -f docker-compose.monolith.yml up -d --build
echo "Waiting for the stack to settle..."
sleep 8

python3 tools/load_test.py --url http://localhost:8080 --label monolith \
    --duration "$DURATION" --concurrency "$CONCURRENCY" --out results_monolith.json

echo "Tearing down monolith..."
docker compose -f docker-compose.monolith.yml down -v

echo ""
echo "=================================================="
echo "Generating comparison report..."
echo "=================================================="
python3 tools/compare_report.py results_scalable.json results_monolith.json --out comparison_report.md

echo ""
echo "Done. See comparison_report.md"
