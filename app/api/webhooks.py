import hmac
import hashlib
import json
import logging
import threading
from typing import Optional, Dict, Any, Tuple
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services.db import get_db_connection, get_global_webhook_secret
from app.services.git_manager import normalize_git_url
from app.services.indexer import sync_single_git_repo

logger = logging.getLogger("contextcortex.webhook")
router = APIRouter()

def verify_hmac_sha256(raw_body: bytes, signature_header: Optional[str], secret: str, prefix: str = "sha256=") -> bool:
    """Verifies HMAC SHA256 signature against raw request body."""
    if not signature_header or not secret:
        return False
    sig = signature_header.strip()
    if prefix and sig.startswith(prefix):
        sig = sig[len(prefix):].strip()
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)

def parse_webhook_payload(payload: Dict[str, Any], headers: Dict[str, str]) -> Tuple[Optional[str], Optional[str]]:
    """Extracts (normalized_repo_url, pushed_branch) from multi-provider webhook payloads."""
    ref = payload.get("ref", "")
    # Bitbucket format: push -> changes -> new -> name
    if not ref and "push" in payload and isinstance(payload["push"], dict):
        changes = payload["push"].get("changes", [])
        if changes and isinstance(changes, list) and len(changes) > 0:
            new_info = changes[0].get("new", {})
            if isinstance(new_info, dict):
                ref = new_info.get("name", "")

    branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref

    repo_url = None
    if "repository" in payload and isinstance(payload["repository"], dict):
        rep = payload["repository"]
        repo_url = rep.get("clone_url") or rep.get("git_url") or rep.get("ssh_url") or rep.get("html_url")
        # Bitbucket links.html.href or links.clone
        if not repo_url and "links" in rep and isinstance(rep["links"], dict):
            links = rep["links"]
            if "html" in links and isinstance(links["html"], dict):
                repo_url = links["html"].get("href")
            elif "clone" in links and isinstance(links["clone"], list):
                for c in links["clone"]:
                    if isinstance(c, dict) and c.get("href"):
                        repo_url = c.get("href")
                        break
    elif "project" in payload and isinstance(payload["project"], dict):  # GitLab
        proj = payload["project"]
        repo_url = proj.get("git_http_url") or proj.get("git_ssh_url") or proj.get("web_url")

    return (normalize_git_url(repo_url) if repo_url else None, branch or None)

@router.post("/api/webhooks/git")
async def handle_git_webhook(request: Request):
    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    global_secret = get_global_webhook_secret()

    # Signature verification if global secret is configured
    if global_secret:
        gh_sig = headers.get("x-hub-signature-256") or headers.get("x-hub-signature")
        gl_token = headers.get("x-gitlab-token")
        gitea_sig = headers.get("x-gitea-signature") or headers.get("x-gitea-signature-256")

        authorized = False
        if gh_sig:
            prefix = "sha256=" if gh_sig.startswith("sha256=") else "sha1=" if gh_sig.startswith("sha1=") else ""
            authorized = verify_hmac_sha256(raw_body, gh_sig, global_secret, prefix=prefix)
        elif gl_token:
            authorized = hmac.compare_digest(gl_token.strip(), global_secret.strip())
        elif gitea_sig:
            prefix = "sha256=" if gitea_sig.startswith("sha256=") else ""
            authorized = verify_hmac_sha256(raw_body, gitea_sig, global_secret, prefix=prefix)

        if not authorized:
            logger.warning("Unauthorized webhook payload received - invalid or missing signature/token")
            return JSONResponse(status_code=401, content={"error": "Invalid webhook signature or token"})

    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        if not isinstance(payload, dict):
            return JSONResponse(status_code=400, content={"error": "Payload must be a JSON object"})
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Invalid JSON payload: {e}"})

    repo_url, pushed_branch = parse_webhook_payload(payload, headers)
    if not repo_url:
        return JSONResponse(status_code=400, content={"error": "Could not identify repository URL from payload"})

    # Match repository in DB
    with get_db_connection() as conn:
        rows = conn.execute("SELECT id, name, url, branch, auto_sync FROM git_repositories").fetchall()

    matched_repo = None
    clean_target_url = repo_url.rstrip("/").removesuffix(".git")

    for r in rows:
        norm_db_url = normalize_git_url(r["url"]).rstrip("/").removesuffix(".git")
        if norm_db_url == clean_target_url:
            # Check branch match if branch present in payload
            if not pushed_branch or r["branch"] == pushed_branch:
                matched_repo = dict(r)
                break

    if not matched_repo:
        logger.info(f"Webhook received for unregistered or non-matching repository: {repo_url} (branch: {pushed_branch})")
        return JSONResponse(status_code=200, content={"status": "ignored", "message": "Repository or branch not registered"})

    if not matched_repo.get("auto_sync", 1):
        logger.info(f"Webhook received for repo '{matched_repo['name']}' but auto-sync is disabled")
        return JSONResponse(status_code=200, content={"status": "ignored", "message": "Auto-sync disabled for this repository"})

    repo_id = matched_repo["id"]
    repo_name = matched_repo["name"]
    logger.info(f"Webhook triggered sync for repository '{repo_name}' (ID: {repo_id}, Branch: {pushed_branch})")
    threading.Thread(target=sync_single_git_repo, args=(repo_id,), daemon=True).start()

    return {"status": "sync_triggered", "repo": repo_name, "id": repo_id}
