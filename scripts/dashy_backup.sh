#!/bin/bash
# dashy_backup.sh
# Version: 1.0
# Description: Weekly backup of Dashy database and billing seed to Dropbox
# Runs via launchd every Sunday; executes on next wake if machine was asleep

set -euo pipefail

BACKUP_DIR="/Users/stevevinter/Dropbox/2tech/Backups/dashy"
DB_PATH="/Users/stevevinter/.personal-dashboard/dashboard.db"
SEED_PATH="/Users/stevevinter/dashy/app/backend/dashy_billing_seed.json"
DATE=$(date '+%Y-%m-%d')
ZIP_NAME="dashy-backup-${DATE}.zip"
TMP_DIR=$(mktemp -d)

# Ensure backup directory exists
mkdir -p "$BACKUP_DIR"

# Skip if today's backup already exists
if [ -f "$BACKUP_DIR/$ZIP_NAME" ]; then
    echo "$(date): Backup already exists for $DATE — skipping." >> /tmp/dashy-backup.log
    exit 0
fi

# Copy files to temp dir
cp "$DB_PATH" "$TMP_DIR/dashboard.db"
cp "$SEED_PATH" "$TMP_DIR/dashy_billing_seed.json"

# Create zip
cd "$TMP_DIR"
zip -q "$BACKUP_DIR/$ZIP_NAME" dashboard.db dashy_billing_seed.json

# Cleanup
rm -rf "$TMP_DIR"

echo "$(date): Backup saved to $BACKUP_DIR/$ZIP_NAME" >> /tmp/dashy-backup.log
