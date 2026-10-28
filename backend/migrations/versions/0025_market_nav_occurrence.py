"""Preserve explicitly versioned AMFI NAV source positions without widening quotas."""

from alembic import op

revision = "0025_market_nav_occurrence"
down_revision = "0024_bank_account_setup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.market_observations
            DROP CONSTRAINT market_observations_occurrence_check,
            DROP CONSTRAINT market_observations_contract_version_check,
            ADD CONSTRAINT market_source_occurrence_contract CHECK (
                (contract_version=1 AND occurrence BETWEEN 1 AND 1000) OR
                (contract_version=2 AND kind='nav' AND namespace='amfi_nav_report'
                    AND occurrence BETWEEN 1 AND 25000)
            )
    """)


def downgrade() -> None:
    # The runner locks forced-RLS tables and exposes their rows to the schema
    # owner within this transaction before evaluating downgrade guards.
    op.execute("LOCK TABLE app.market_observations IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $f$ BEGIN
            IF EXISTS (SELECT 1 FROM app.market_observations
                WHERE contract_version<>1 OR occurrence NOT BETWEEN 1 AND 1000) THEN
                RAISE EXCEPTION 'Retained market evidence requires a forward migration';
            END IF;
        END $f$
    """)
    op.execute("""
        ALTER TABLE app.market_observations
            DROP CONSTRAINT market_source_occurrence_contract,
            ADD CONSTRAINT market_observations_occurrence_check
                CHECK (occurrence BETWEEN 1 AND 1000),
            ADD CONSTRAINT market_observations_contract_version_check
                CHECK (contract_version=1)
    """)
