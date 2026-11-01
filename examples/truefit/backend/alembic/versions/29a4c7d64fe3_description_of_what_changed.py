"""description of what changed

Revision ID: 29a4c7d64fe3
Revises:
Create Date: 2026-03-04 11:38:41.461989

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "29a4c7d64fe3"
down_revision: Union[str, Sequence[str], None] = "a59adafa3609"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Superseded by the consolidated initial schema migration."""
    pass


def downgrade() -> None:
    """No-op; the superseded branch never owns schema state."""
    pass
