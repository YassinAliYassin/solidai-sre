#!/bin/bash
CF_TOKEN="cfat...ZONE_ID="5e3c1a3b5e4cd3b67545feeb1136fb62"

echo "=== Checking zone status ==="
ZONE_STATUS=$(curl -s "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}" \
  -H "Authorization: Bearer *** \
  -H "Content-Type: application/json")

echo "$ZONE_STATUS" | python3 -m json.tool

STATUS=$(echo "$ZONE_STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('result',{}).get('status','unknown'))" 2>/dev/null)
echo ""
echo "Zone status: $STATUS"

if [ "$STATUS" = "active" ]; then
  echo ""
  echo "=== Zone is active. Purging cache ==="
  PURGE_RESULT=$(curl -s -X POST "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/purge_cache" \
    -H "Authorization: Bearer *** \
    -H "Content-Type: application/json" \
    --data '{"purge_everything": true}')
  echo "$PURGE_RESULT" | python3 -m json.tool

  echo ""
  echo "=== Checking site keywords ==="
  curl -s https://fresh-people.co.za | grep -i "keywords" || echo "No 'keywords' found in page source"
else
  echo "Zone is NOT active (status: $STATUS). Skipping cache purge."
fi
