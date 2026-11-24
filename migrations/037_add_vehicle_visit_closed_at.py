"""Allow an explicitly confirmed departure to end vehicle reidentification."""


def migrate(migrator, database, fake=False, **kwargs):
    migrator.sql("ALTER TABLE vehiclevisit ADD COLUMN closed_at REAL NULL")


def rollback(migrator, database, fake=False, **kwargs):
    migrator.sql("ALTER TABLE vehiclevisit DROP COLUMN closed_at")
