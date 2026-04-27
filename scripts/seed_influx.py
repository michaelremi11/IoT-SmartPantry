#!/usr/bin/env python3
"""
Legacy notice.

InfluxDB is no longer part of the active Smart Pantry runtime. Sensor and
inventory event data now live in Firestore collections:

  - environmentLogs
  - usageLogs

Use scripts/seed_mock_analytics.py for Firestore analytics seed data.
"""

print(__doc__.strip())
