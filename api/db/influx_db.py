"""
Legacy compatibility module.

InfluxDB was retired from the active Smart Pantry data path.  Sensor readings,
inventory actions, and analytics inputs now live in Firestore so web and
mobile clients can share one realtime source of truth.
"""


def _removed():
    raise RuntimeError(
        "InfluxDB is no longer configured. Use Firestore collections "
        "environmentLogs and usageLogs instead."
    )


def get_influx_client():
    _removed()


def get_influx_write_api():
    _removed()


def get_influx_query_api():
    _removed()
