"""Lightweight Snowflake connector with RSA key authentication."""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
import snowflake.connector

from guardrail.config import SnowflakeConfig


class SnowflakeClient:
    """Manages a Snowflake connection with RSA key auth. Connection is lazy."""

    def __init__(self, config: SnowflakeConfig):
        self._config = config
        self._conn: snowflake.connector.SnowflakeConnection | None = None

    def _load_private_key(self) -> bytes:
        key_path = Path(self._config.private_key_file).expanduser()
        with open(key_path, "rb") as f:
            key_data = f.read()
        private_key = serialization.load_pem_private_key(
            key_data, password=None, backend=default_backend()
        )
        return private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def _connect(self) -> snowflake.connector.SnowflakeConnection:
        if self._conn is not None:
            return self._conn
        pk_bytes = self._load_private_key()
        self._conn = snowflake.connector.connect(
            account=self._config.account,
            user=self._config.user,
            private_key=pk_bytes,
            warehouse=self._config.warehouse,
            role=self._config.role,
        )
        return self._conn

    def execute(self, sql: str) -> list[dict]:
        """Execute SQL and return results as list of dicts."""
        conn = self._connect()
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        finally:
            cursor.close()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
