"""Version preference writes without broadening runtime column privileges."""

from alembic import op

revision = "0005_preference_revisions"
down_revision = "0004_browser_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.workspace_preferences
        ADD COLUMN revision bigint NOT NULL DEFAULT 1
        CHECK (revision BETWEEN 1 AND 9007199254740991)
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION app.touch_workspace_preferences() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog
        AS $function$
        BEGIN
            NEW.updated_at := statement_timestamp();
            NEW.revision := OLD.revision + 1;
            RETURN NEW;
        END
        $function$
    """)


def downgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION app.touch_workspace_preferences() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog
        AS $function$
        BEGIN
            NEW.updated_at := statement_timestamp();
            RETURN NEW;
        END
        $function$
    """)
    op.execute("ALTER TABLE app.workspace_preferences DROP COLUMN revision")
