#!/bin/bash
# entrypoint.sh

while true; do
    echo "Starting email fetch..."
    python /app/email_fetcher.py
    echo "Sleeping for ${FETCH_INTERVAL:-3600} seconds..."
    sleep ${FETCH_INTERVAL:-3600}
done