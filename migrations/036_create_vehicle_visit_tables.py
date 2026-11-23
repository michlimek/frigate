"""Add durable vehicle visits and original event links."""


def migrate(migrator, database, fake=False, **kwargs):
    migrator.sql("""
        CREATE TABLE IF NOT EXISTS vehiclevisit (
            id VARCHAR(30) NOT NULL PRIMARY KEY,
            camera VARCHAR(20) NOT NULL,
            start_time REAL NOT NULL,
            last_seen REAL NOT NULL,
            reference_hash VARCHAR(16),
            reference_box JSON,
            license_plate VARCHAR(100),
            samples JSON NOT NULL
        )
    """)
    migrator.sql(
        "CREATE INDEX IF NOT EXISTS vehiclevisit_camera_start "
        "ON vehiclevisit (camera, start_time DESC)"
    )
    migrator.sql("""
        CREATE TABLE IF NOT EXISTS vehiclevisitevent (
            event_id VARCHAR(30) NOT NULL PRIMARY KEY,
            visit_id VARCHAR(30) NOT NULL,
            match_reason VARCHAR(48) NOT NULL,
            start_time REAL NOT NULL
        )
    """)
    migrator.sql(
        "CREATE INDEX IF NOT EXISTS vehiclevisitevent_visit_id "
        "ON vehiclevisitevent (visit_id)"
    )


def rollback(migrator, database, fake=False, **kwargs):
    migrator.sql("DROP TABLE IF EXISTS vehiclevisitevent")
    migrator.sql("DROP TABLE IF EXISTS vehiclevisit")
