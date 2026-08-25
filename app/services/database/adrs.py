import logging
from typing import Optional, List, Dict, Any
from app.services.database.connection import get_db_connection

logger = logging.getLogger("contextcortex.db")

def get_adr(adr_id: str, repo: Optional[str] = None) -> Optional[Dict[str, Any]]:
    try:
        with get_db_connection() as conn:
            if repo:
                row = conn.execute(
                    "SELECT * FROM architecture_decision_records WHERE id = ? AND repo = ?",
                    (adr_id, repo)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM architecture_decision_records WHERE id = ?",
                    (adr_id,)
                ).fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get ADR {adr_id}: {e}")
        return None

def list_adrs(repo: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        with get_db_connection() as conn:
            query = "SELECT * FROM architecture_decision_records WHERE repo = ?"
            params = [repo]
            if status:
                query += " AND status = ?"
                params.append(status.upper().strip())
            query += " ORDER BY id ASC"
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to list ADRs for repo {repo}: {e}")
        return []

def create_adr(
    repo: str,
    title: str,
    status: str = "PROPOSED",
    context: str = "",
    decision: str = "",
    consequences: Optional[str] = None,
    superseded_by: Optional[str] = None,
    adr_id: Optional[str] = None
) -> Dict[str, Any]:
    try:
        with get_db_connection() as conn:
            if not adr_id:
                count_row = conn.execute(
                    "SELECT count(*) FROM architecture_decision_records WHERE repo = ?",
                    (repo,)
                ).fetchone()
                seq = (count_row[0] if count_row else 0) + 1
                adr_id = f"ADR-{seq:03d}"
                while conn.execute("SELECT 1 FROM architecture_decision_records WHERE id = ?", (adr_id,)).fetchone():
                    seq += 1
                    adr_id = f"ADR-{seq:03d}"

            status_clean = status.upper().strip()
            conn.execute(
                """INSERT INTO architecture_decision_records (id, repo, title, status, context, decision, consequences, superseded_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (adr_id, repo, title, status_clean, context, decision, consequences, superseded_by)
            )
            conn.commit()
            return get_adr(adr_id, repo) or {}
    except Exception as e:
        logger.error(f"Failed to create ADR: {e}")
        raise

def update_adr(
    adr_id: str,
    repo: str,
    title: Optional[str] = None,
    status: Optional[str] = None,
    context: Optional[str] = None,
    decision: Optional[str] = None,
    consequences: Optional[str] = None,
    superseded_by: Optional[str] = None
) -> Dict[str, Any]:
    try:
        existing = get_adr(adr_id, repo)
        if not existing:
            raise ValueError(f"ADR '{adr_id}' not found for repository '{repo}'.")

        new_title = title if title is not None else existing["title"]
        new_status = status.upper().strip() if status is not None else existing["status"]
        new_context = context if context is not None else existing["context"]
        new_decision = decision if decision is not None else existing["decision"]
        new_consequences = consequences if consequences is not None else existing["consequences"]
        new_superseded_by = superseded_by if superseded_by is not None else existing["superseded_by"]

        with get_db_connection() as conn:
            conn.execute(
                """UPDATE architecture_decision_records
                   SET title = ?, status = ?, context = ?, decision = ?, consequences = ?, superseded_by = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND repo = ?""",
                (new_title, new_status, new_context, new_decision, new_consequences, new_superseded_by, adr_id, repo)
            )
            conn.commit()

        return get_adr(adr_id, repo) or {}
    except Exception as e:
        logger.error(f"Failed to update ADR {adr_id}: {e}")
        raise

def supersede_adr(old_id: str, new_id: str, repo: str) -> Dict[str, Any]:
    try:
        old_adr = get_adr(old_id, repo)
        if not old_adr:
            raise ValueError(f"Target ADR '{old_id}' to supersede does not exist in repo '{repo}'.")
        new_adr = get_adr(new_id, repo)
        if not new_adr:
            raise ValueError(f"Superseding ADR '{new_id}' does not exist in repo '{repo}'.")

        with get_db_connection() as conn:
            conn.execute(
                """UPDATE architecture_decision_records
                   SET status = 'SUPERSEDED', superseded_by = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND repo = ?""",
                (new_id, old_id, repo)
            )
            conn.commit()

        return get_adr(old_id, repo) or {}
    except Exception as e:
        logger.error(f"Failed to supersede ADR {old_id} with {new_id}: {e}")
        raise

def upsert_adr(
    adr_id: str,
    repo: str,
    title: str,
    status: str,
    context: str,
    decision: str,
    consequences: Optional[str] = None,
    superseded_by: Optional[str] = None
) -> Dict[str, Any]:
    try:
        status_clean = status.upper().strip()
        with get_db_connection() as conn:
            conn.execute(
                """INSERT INTO architecture_decision_records (id, repo, title, status, context, decision, consequences, superseded_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                   ON CONFLICT(id) DO UPDATE SET
                       repo = excluded.repo,
                       title = excluded.title,
                       status = excluded.status,
                       context = excluded.context,
                       decision = excluded.decision,
                       consequences = excluded.consequences,
                       superseded_by = excluded.superseded_by,
                       updated_at = CURRENT_TIMESTAMP""",
                (adr_id, repo, title, status_clean, context, decision, consequences, superseded_by)
            )
            conn.commit()
        return get_adr(adr_id, repo) or {}
    except Exception as e:
        logger.error(f"Failed to upsert ADR {adr_id}: {e}")
        raise
