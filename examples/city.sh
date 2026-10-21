#!/usr/bin/env bash
# End-to-end crawl of one city centre, from category to exportable JSONL.
#
#   ./examples/city.sh 41.8902 12.4922 rome
#
# Edit USER_AGENT: Wikimedia requires a real contact address.

set -euo pipefail

LAT=${1:-41.8902}
LON=${2:-12.4922}
NAME=${3:-rome}
USER_AGENT="wikicrawl-example/0.1 (https://github.com/; example@example.org)"

python3 -m wikicrawl collect \
  --lat "$LAT" --lon "$LON" \
  --radius 400 --cell 100 --limit 300 \
  --db "$NAME.sqlite" --user-agent "$USER_AGENT"

python3 -m wikicrawl photos --db "$NAME.sqlite" --user-agent "$USER_AGENT"
python3 -m wikicrawl stats --db "$NAME.sqlite"
python3 -m wikicrawl export --db "$NAME.sqlite" --out "$NAME.jsonl"

echo "wrote $NAME.jsonl"
