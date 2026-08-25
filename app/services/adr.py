import os
import re
import logging
from typing import Dict, Any, Optional
import frontmatter

from app.services.db import upsert_adr

logger = logging.getLogger("contextcortex.adr")

VALID_STATUSES = {"PROPOSED", "ACCEPTED", "REJECTED", "SUPERSEDED", "DEPRECATED"}

def parse_adr_markdown(content: str, filepath: str, repo: str) -> Dict[str, Any]:
    """
    Parses a Michael Nygard or MADR (Markdown Architectural Decision Records) document.
    Extracts id, title, status, context, decision, consequences, superseded_by.
    """
    meta = {}
    body = content
    try:
        post = frontmatter.loads(content)
        meta = post.metadata or {}
        body = post.content
    except Exception:
        body = content

    filename = os.path.basename(filepath)
    filename_no_ext = os.path.splitext(filename)[0]

    # Extract ID
    adr_id = meta.get("id") or meta.get("number")
    if not adr_id:
        m_id = re.search(r"^(ADR-\d+|\d+)", filename_no_ext, re.IGNORECASE)
        if m_id:
            raw_id = m_id.group(1).upper()
            if not raw_id.startswith("ADR-"):
                try:
                    adr_id = f"ADR-{int(raw_id):03d}"
                except ValueError:
                    adr_id = f"ADR-{raw_id}"
            else:
                adr_id = raw_id
        else:
            adr_id = filename_no_ext.upper()

    # Extract Title
    title = meta.get("title")
    if not title:
        m_title = re.search(r"^#\s+(?:ADR-\d+[:\s]+|\d+[\.\s]+)?(.+)", body, re.MULTILINE)
        if m_title:
            title = m_title.group(1).strip()
        else:
            title = filename_no_ext.replace("-", " ").replace("_", " ").title()

    # Extract Sections using H2 headings
    sections = {}
    current_section = None
    section_lines = []

    lines = body.splitlines()
    for line in lines:
        h2_match = re.match(r"^##\s+(.+)$", line)
        if h2_match:
            if current_section:
                sections[current_section] = "\n".join(section_lines).strip()
            current_section = h2_match.group(1).strip().lower()
            section_lines = []
        elif current_section:
            section_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(section_lines).strip()

    # Extract Status and superseded_by
    raw_status = meta.get("status")
    superseded_by = meta.get("superseded_by") or meta.get("superseded-by")

    if not raw_status:
        # Search sections for status
        for sec_name, sec_text in sections.items():
            if "status" in sec_name:
                raw_status = sec_text
                break

    if not raw_status:
        # Check inline status
        m_stat = re.search(r"(?:Status|Status:)\s*([A-Za-z0-9_\-\s\[\]\(\)\.\:]+)", body, re.IGNORECASE)
        if m_stat:
            raw_status = m_stat.group(1).strip()

    status = "PROPOSED"
    if raw_status:
        raw_upper = raw_status.upper()
        if "SUPERSEDED" in raw_upper:
            status = "SUPERSEDED"
            if not superseded_by:
                m_sup = re.search(r"(?:superseded by|superseded-by)\s+\[?([A-Za-z0-9_\-]+)\]?", raw_status, re.IGNORECASE)
                if m_sup:
                    superseded_by = m_sup.group(1).upper()
        elif "ACCEPTED" in raw_upper:
            status = "ACCEPTED"
        elif "REJECTED" in raw_upper:
            status = "REJECTED"
        elif "DEPRECATED" in raw_upper:
            status = "DEPRECATED"
        elif "PROPOSED" in raw_upper:
            status = "PROPOSED"

    if superseded_by:
        superseded_by = str(superseded_by).upper().strip()
        if not superseded_by.startswith("ADR-") and superseded_by.isdigit():
            superseded_by = f"ADR-{int(superseded_by):03d}"

    # Extract Context
    context = meta.get("context", "")
    if not context:
        for sec_name, sec_text in sections.items():
            if "context" in sec_name or "problem" in sec_name:
                context = sec_text
                break

    # Extract Decision
    decision = meta.get("decision", "")
    if not decision:
        for sec_name, sec_text in sections.items():
            if "decision" in sec_name or "outcome" in sec_name:
                decision = sec_text
                break

    # Extract Consequences
    consequences = meta.get("consequences", "")
    if not consequences:
        for sec_name, sec_text in sections.items():
            if "consequences" in sec_name or "options" in sec_name:
                consequences = sec_text
                break

    if not context and not decision:
        # Fallback body
        context = body[:500]
        decision = "Refer to document content."

    return {
        "id": str(adr_id),
        "repo": repo,
        "title": title,
        "status": status,
        "context": context,
        "decision": decision,
        "consequences": consequences or None,
        "superseded_by": superseded_by or None,
    }

def sync_adr_file(filepath: str, repo: str, content: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Reads or receives ADR markdown file content and syncs it to SQLite database."""
    try:
        if content is None:
            if not os.path.exists(filepath):
                return None
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

        parsed = parse_adr_markdown(content, filepath, repo)
        res = upsert_adr(
            adr_id=parsed["id"],
            repo=parsed["repo"],
            title=parsed["title"],
            status=parsed["status"],
            context=parsed["context"],
            decision=parsed["decision"],
            consequences=parsed["consequences"],
            superseded_by=parsed["superseded_by"]
        )
        return res
    except Exception as e:
        logger.error(f"Error syncing ADR file {filepath} for repo {repo}: {e}")
        return None
