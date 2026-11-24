"""HTTP layer shared by the local server (server.py) and the Vercel functions (api/*.py).

handle(method, path, headers, body) -> (status, headers, body bytes)
"""
import base64
import binascii
import json
import os
import threading
import time

from .analyze import StepError, VERSIONS, analyze, settings_from_env
from .ad import extract_ad
from .goal import GOAL_VERSION, GOAL_VERSION_V2, MAX_GOAL, interpret_goal
from .meta import MetaError, client_from_env

MAX_BODY = int(os.environ.get("MAX_BODY_BYTES", "4400000"))  # Vercel caps request bodies at 4.5 MB
MIMES = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif", b"RIFF": "image/webp"}

_hits, _lock = {}, threading.Lock()


def _json(status, obj, extra=None):
    h = {"Content-Type": "application/json", **_cors(), **(extra or {})}
    return status, h, json.dumps(obj, indent=2).encode()


def _cors():
    return {"Access-Control-Allow-Origin": os.environ.get("ALLOW_ORIGIN", "*"),
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Service-Token",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS"}


def _error(status, code, message, **more):
    return _json(status, {"error": {"code": code, "message": message, **more}})


def _header(headers, name):
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


def _authorized(headers):
    token = os.environ.get("SERVICE_TOKEN", "").strip()
    if not token:
        return True
    auth = _header(headers, "Authorization") or ""
    return auth == f"Bearer {token}" or (_header(headers, "X-Service-Token") or "") == token


def _rate_limited(headers):
    limit = int(os.environ.get("RATE_LIMIT_PER_HOUR", "60") or 0)
    if limit <= 0:
        return False
    ip = (_header(headers, "X-Forwarded-For") or _header(headers, "X-Real-Ip") or "local").split(",")[0].strip()
    now = time.time()
    with _lock:
        recent = [t for t in _hits.get(ip, []) if now - t < 3600]
        if len(recent) >= limit:
            _hits[ip] = recent
            return True
        _hits[ip] = recent + [now]
    return False


def _decode_image(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Send the screenshot as a base64 string in \"image\" (a data: URL works too).")
    if value.startswith("data:"):
        value = value.split(",", 1)[-1]
    try:
        raw = base64.b64decode(value, validate=False)
    except (binascii.Error, ValueError):
        raise ValueError("\"image\" is not valid base64.")
    mime = next((m for sig, m in MIMES.items() if raw.startswith(sig)), None)
    if not mime:
        raise ValueError("The image must be PNG, JPEG, WebP or GIF.")
    return raw, mime


def health():
    client = client_from_env()
    return _json(200, {"ok": True, "mode": client.mode if client else "not configured",
                       "model_key_set": bool(os.environ.get("MODEL_API_KEY", "").strip()),
                       "token_required": bool(os.environ.get("SERVICE_TOKEN", "").strip()),
                       "settings": settings_from_env(), "versions": {**VERSIONS, "goal_prompt": GOAL_VERSION, "goal_prompt_v2": GOAL_VERSION_V2}})


def handle(method, path, headers, body):
    path = path.split("?", 1)[0].rstrip("/") or "/"
    if method == "OPTIONS":
        return 204, _cors(), b""
    if path == "/api/health" and method == "GET":
        return health()
    if path not in ("/api/analyze", "/api/goal", "/api/ad"):
        return _error(404, "not_found", f"No route for {method} {path}. Use POST /api/analyze, POST /api/goal or GET /api/health.")
    if method != "POST":
        return _error(405, "method_not_allowed", f"Use POST {path}.")
    if not _authorized(headers):
        supplied = bool((_header(headers, "Authorization") or "").strip() or
                        (_header(headers, "X-Service-Token") or "").strip())
        if supplied:
            return _error(401, "invalid_service_token",
                          "The access token was rejected. Check the SERVICE_TOKEN for this Preview environment; do not use a model, Stripe or Supabase key.")
        return _error(401, "missing_service_token",
                      "This preview requires an access token. Open Settings and enter its SERVICE_TOKEN before submitting.")
    if len(body) > MAX_BODY:
        return _error(413, "too_large", f"Request is {len(body)} bytes; the limit is {MAX_BODY}. Send a smaller or JPEG screenshot.")
    if _rate_limited(headers):
        return _error(429, "rate_limited", "Too many requests from this address in the last hour.")
    if path == "/api/goal":
        return _goal(body)
    try:
        req = json.loads(body or b"{}")
        image, mime = _decode_image(req.get("image"))
    except ValueError as e:
        return _error(400, "bad_request", str(e) if "JSON" not in str(e) else "Body must be JSON.")
    if path == "/api/ad":
        client = client_from_env()
        if client is None:
            return _error(503, "not_configured", "A model key is required to extract advertising claims.")
        try:
            return _json(200, extract_ad(image, mime, client))
        except MetaError as e:
            return _error(502, "model_call_failed", str(e), step="ad_extraction", http_status=e.status)
    review = req.get("review", "auto")
    if review not in ("auto", "always", "never"):
        return _error(400, "bad_request", "\"review\" must be auto, always or never.")
    client = client_from_env()
    if client is None:
        return _error(503, "not_configured", "MODEL_API_KEY is not set on the server. Set it, or set MOCK=1 to try the sample screenshots.")
    try:
        result = analyze(image, mime, req.get("question"), client, settings_from_env(), review)
    except StepError as e:
        return _error(502, "model_call_failed", str(e.err), step=e.step, http_status=e.err.status,
                      detail=e.err.body, calls_before_failure=e.calls)
    return _json(200, result)


def _goal(body):
    """POST /api/goal: Muse Spark reads a shopper's goal and picks from the editorial library."""
    try:
        req = json.loads(body or b"{}")
    except ValueError:
        return _error(400, "bad_request", "Body must be JSON.")
    goal = req.get("goal") if isinstance(req, dict) else None
    if not isinstance(goal, str) or not goal.strip():
        return _error(400, "bad_request", "Say what you are trying to do first: send it as \"goal\".")
    if len(goal) > MAX_GOAL:
        return _error(400, "bad_request", f"Keep the goal under {MAX_GOAL} characters.")
    version = req.get("version", 1)
    if version not in (1, 2):
        return _error(400, "bad_request", "version must be 1 or 2.")
    owned = req.get("ownedTools", [])
    if not isinstance(owned, list) or not all(isinstance(x, str) for x in owned):
        return _error(400, "bad_request", "ownedTools must be a list of tool names.")
    client = client_from_env()
    if client is None:
        return _error(503, "not_configured", "MODEL_API_KEY is not set on the server. Set it, or set MOCK=1 for sample answers.")
    try:
        return _json(200, interpret_goal(goal, client, settings_from_env(), owned, version))
    except MetaError as e:
        return _error(502, "model_call_failed", str(e), step="goal", http_status=e.status, detail=e.body)
