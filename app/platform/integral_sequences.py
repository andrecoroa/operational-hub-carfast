"""Reconstruct target-only sequence state without reading source sequences."""

from __future__ import annotations

from sqlalchemy import MetaData, text
from sqlalchemy.engine import Connection
from sqlalchemy.sql.sqltypes import BigInteger, Integer, SmallInteger


def next_sequence_state(maximum: int | None) -> tuple[int, bool]:
    """Return setval(value, is_called) so nextval is collision-free."""
    if maximum is None:
        return 1, False
    return maximum, True


def reset_target_sequences(connection: Connection, metadata: MetaData) -> int:
    """Set owned integer-PK sequences from target table maxima in one transaction."""
    reset = 0
    for table_name in sorted(metadata.tables):
        table = metadata.tables[table_name]
        for column in table.primary_key.columns:
            if not isinstance(column.type, (SmallInteger, Integer, BigInteger)):
                continue
            relation = f'public."{table.name.replace(chr(34), chr(34) * 2)}"'
            sequence = connection.execute(
                text("SELECT pg_get_serial_sequence(:relation, :column)"),
                {"relation": relation, "column": column.name},
            ).scalar_one()
            if sequence is None:
                continue
            maximum = connection.execute(
                text(
                    f'SELECT max("{column.name.replace(chr(34), chr(34) * 2)}") '
                    f'FROM "{table.name.replace(chr(34), chr(34) * 2)}"'
                )
            ).scalar_one()
            value, called = next_sequence_state(maximum)
            connection.execute(
                text("SELECT setval(CAST(:sequence AS regclass), :value, :called)"),
                {"sequence": sequence, "value": value, "called": called},
            )
            reset += 1
    return reset
