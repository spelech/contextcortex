import logging
from typing import Any, Optional, Tuple, Dict, List
from sqlalchemy import text

logger = logging.getLogger("contextcortex.database.postgres_compat")


class DictRow(dict):
    """
    Dictionary subclass providing compatibility with sqlite3.Row access patterns:
    - Key lookup: row["col"]
    - Positional lookup: row[0]
    - Attribute lookup: row.col
    - Dict conversion: dict(row)
    """
    def __init__(self, mapping: dict, tuple_vals: Optional[tuple] = None):
        super().__init__(mapping)
        self._tuple_vals = tuple_vals if tuple_vals is not None else tuple(mapping.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._tuple_vals[key]
        return super().__getitem__(key)

    def __getattr__(self, name):
        if name in self:
            return self[name]
        raise AttributeError(f"'DictRow' object has no attribute '{name}'")


TABLES_WITH_ID = {
    "git_repositories",
    "indexed_paths",
    "git_host_credentials",
    "ast_symbols",
    "ast_relationships",
    "api_routes",
    "api_client_calls",
    "custom_prompts",
    "api_keys",
}


def _convert_sql_placeholders(sql: str, params: Any = None) -> tuple:
    if not isinstance(sql, str):
        return sql, params

    clean_sql = sql.strip()

    sql_upper = clean_sql.upper()
    if sql_upper.startswith("INSERT") and "RETURNING" not in sql_upper:
        for tbl in TABLES_WITH_ID:
            if tbl in clean_sql:
                clean_sql = clean_sql.rstrip(";") + " RETURNING id"
                break

    if params is None:
        return clean_sql, None

    if isinstance(params, dict):
        return clean_sql, params

    if isinstance(params, (tuple, list)):
        if "?" not in clean_sql:
            return clean_sql, params
        parts = clean_sql.split("?")
        if len(parts) - 1 != len(params):
            return clean_sql, params
        param_dict = {}
        new_parts = []
        for i, part in enumerate(parts[:-1]):
            pname = f"p{i+1}"
            param_dict[pname] = params[i]
            new_parts.append(part)
            new_parts.append(f":{pname}")
        new_parts.append(parts[-1])
        return "".join(new_parts), param_dict

    return clean_sql, params


class _SingleRowResult:
    def __init__(self, row_dict: Optional[dict]):
        self._row_dict = row_dict
        self._consumed = False

    def mappings(self):
        return self

    def fetchone(self):
        if self._consumed or self._row_dict is None:
            return None
        self._consumed = True
        return self._row_dict

    def fetchall(self):
        if self._consumed or self._row_dict is None:
            return []
        self._consumed = True
        return [self._row_dict]


class PostgresResultAdapter:
    def __init__(self, sa_result: Any, lastrowid: Optional[Any] = None):
        self._sa_result = sa_result
        self.lastrowid = lastrowid
        if hasattr(sa_result, "rowcount"):
            self.rowcount = sa_result.rowcount
        else:
            self.rowcount = -1

    def fetchone(self) -> Optional[DictRow]:
        if self._sa_result is None:
            return None
        try:
            row = self._sa_result.mappings().fetchone()
            if row is None:
                return None
            return DictRow(dict(row))
        except Exception:
            return None

    def fetchall(self) -> list:
        if self._sa_result is None:
            return []
        try:
            rows = self._sa_result.mappings().fetchall()
            return [DictRow(dict(r)) for r in rows]
        except Exception:
            return []


class PostgresCursorAdapter:
    def __init__(self, conn_adapter: "PostgresConnectionAdapter"):
        self._conn_adapter = conn_adapter
        self.lastrowid = None
        self.rowcount = -1
        self._last_result = None

    def execute(self, sql: Any, params: Any = None):
        res = self._conn_adapter.execute(sql, params)
        self.lastrowid = res.lastrowid
        self.rowcount = res.rowcount
        self._last_result = res
        return res

    def executemany(self, sql: str, param_list: list):
        res = self._conn_adapter.executemany(sql, param_list)
        self.lastrowid = res.lastrowid
        self.rowcount = res.rowcount
        self._last_result = res
        return res

    def fetchone(self):
        if self._last_result:
            return self._last_result.fetchone()
        return None

    def fetchall(self):
        if self._last_result:
            return self._last_result.fetchall()
        return []

    def close(self):
        pass


class PostgresConnectionAdapter:
    def __init__(self, sa_conn=None, engine=None):
        from app.services.database.engine import get_db_engine
        self._engine = engine or get_db_engine()
        self._sa_conn = sa_conn or self._engine.connect()
        self._closed = False

    def cursor(self):
        return PostgresCursorAdapter(self)

    def execute(self, sql: Any, params: Any = None):
        if isinstance(sql, str):
            converted_sql, converted_params = _convert_sql_placeholders(sql, params)
            is_insert = converted_sql.strip().upper().startswith("INSERT") and "RETURNING" in converted_sql.upper()
            if converted_params is not None:
                sa_res = self._sa_conn.execute(text(converted_sql), converted_params)
            else:
                sa_res = self._sa_conn.execute(text(converted_sql))

            lastrowid = None
            if is_insert:
                try:
                    row = sa_res.mappings().fetchone()
                    if row:
                        lastrowid = row.get("id") or (list(row.values())[0] if row else None)
                        sa_res = _SingleRowResult(dict(row))
                except Exception:
                    pass
            return PostgresResultAdapter(sa_res, lastrowid=lastrowid)
        else:
            sa_res = self._sa_conn.execute(sql, params) if params else self._sa_conn.execute(sql)
            return PostgresResultAdapter(sa_res)

    def executemany(self, sql: str, param_list: list):
        if not param_list:
            return PostgresResultAdapter(None)
        if isinstance(param_list[0], (tuple, list)):
            converted_sql, _ = _convert_sql_placeholders(sql, param_list[0])
            converted_param_list = []
            for p in param_list:
                _, p_dict = _convert_sql_placeholders(sql, p)
                converted_param_list.append(p_dict if isinstance(p_dict, dict) else p)
        else:
            converted_sql = sql
            converted_param_list = param_list

        sa_res = self._sa_conn.execute(text(converted_sql), converted_param_list)
        return PostgresResultAdapter(sa_res)

    def commit(self):
        try:
            self._sa_conn.commit()
        except Exception:
            pass

    def rollback(self):
        try:
            self._sa_conn.rollback()
        except Exception:
            pass

    def close(self):
        if not self._closed:
            try:
                self._sa_conn.close()
            except Exception:
                pass
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
