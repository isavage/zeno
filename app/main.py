import json
import os
import uuid
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Dict, Any
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException, status, Depends, APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.security.auth import oauth, is_email_authorized, get_current_user, get_current_admin_user, is_admin_user
from app.agent.usage import usage_store
from app.agent.core import zeno_agent
from app.agent.memory import memory_store
from app.voice.stt import stt_engine
from app.voice import tts_engine
from app.channels.telegram_bot import telegram_manager

from app.agent import prefs
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("zeno")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start Telegram bot background task
    logger.info("Initializing Zeno Personal Assistant...")
    # Initialize vault directory
    _ = settings.vault_path

    # Start Telegram bot polling if token provided
    try:
        await telegram_manager.start()
    except Exception as e:
        logger.error(f"Error starting Telegram bot: {e}")

    yield

    # Shutdown: Stop Telegram bot
    logger.info("Shutting down Zeno...")
    try:
        await telegram_manager.stop()
    except Exception as e:
        logger.error(f"Error stopping Telegram bot: {e}")

app = FastAPI(
    title="Zeno Personal Assistant",
    description="Privacy-first, self-hosted AI assistant with voice and multi-channel access.",
    version="1.0.0",
    lifespan=lifespan
)

# Session middleware for auth
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.APP_SECRET_KEY,
    max_age=14 * 86400,
    same_site="lax",
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(CORSMiddleware,
    allow_origins=[f"https://{host}" for host in settings.allowed_hosts],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files & Templates
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "web" / "static")), name="static")
jinja_templates = Jinja2Templates(directory=str(BASE_DIR / "web" / "templates"))

# Audio temporary cache dir
AUDIO_CACHE_DIR = Path(tempfile.gettempdir()) / "zeno_audio_cache"
AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ----------------- Health & Status -----------------

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "zeno",
        "telegram_enabled": bool(settings.TELEGRAM_BOT_TOKEN),
        "oauth_providers": {
            "google": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
            "microsoft": bool(settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET),
        },
    }

# ----------------- Web UI & Authentication -----------------

# ----------------- Admin API for model defaults -----------------
admin_router = APIRouter(prefix="/admin", tags=["admin"])

def build_redirect_uri(request: Request, path: str) -> str:
    """Build an absolute redirect URI using the current request origin."""
    forwarded_host = request.headers.get("x-forwarded-host")
    forwarded_proto = request.headers.get("x-forwarded-proto")

    host = (forwarded_host or request.headers.get("host") or request.url.netloc).split(",")[0].strip()
    scheme = (forwarded_proto or request.url.scheme).split(",")[0].strip()
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{scheme}://{host}{normalized_path}"


def sse_frame(event: str, payload: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

@admin_router.get("")
@admin_router.get("/")
async def admin_home(request: Request, user: Dict[str, Any] = Depends(get_current_admin_user)):
    return jinja_templates.TemplateResponse(
        request,
        "admin_home.html",
        {
            "user": user,
            "admin_user": True,
        },
    )


@admin_router.get("/models")
def list_models(_: Dict[str, Any] = Depends(get_current_admin_user)):
    """Return a dict of provider -> list of model identifiers.
    This is a static list; extend as needed.
    """
    return {
        "available_models": {
            "openrouter": [
                "nousresearch/hermes-3-llama-3.1-8b",
                "meta-llama/llama-3.3-70b-instruct:free",
            ],
            "openai": ["gpt-4o", "gpt-4o-mini"],
            "deepseek": ["deepseek-chat"],
            "kimi": ["moonshot-v1-32k"],
        }
    }

@admin_router.get("/defaults")
def get_defaults(_: Dict[str, Any] = Depends(get_current_admin_user)):
    return prefs.get_prefs()

@admin_router.post("/defaults")
def set_defaults(
    fast_model: str,
    reasoning_model: str,
    fallback_model: str,
    _: Dict[str, Any] = Depends(get_current_admin_user),
):
    # Basic validation against known models
    known = set()
    for prov_models in list_models()["available_models"].values():
        known.update(prov_models)
    for m in (fast_model, reasoning_model, fallback_model):
        if m not in known:
            raise HTTPException(status_code=400, detail=f"Model '{m}' is not recognized")
    prefs.set_prefs(fast_model, reasoning_model, fallback_model)
    return {"status": "ok", "message": "Preferences saved"}

@admin_router.get("/usage", response_class=HTMLResponse)
def admin_usage(request: Request, _: Dict[str, Any] = Depends(get_current_admin_user)):
    """Render admin usage dashboard showing per‑user token usage."""
    usage_data = usage_store.get_all()
    return jinja_templates.TemplateResponse(
        request,
        "admin_usage.html",
        {"usage": usage_data},
    )

app.include_router(admin_router)

# Settings page – simple UI to edit defaults (template to be created at templates/settings.html)
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user: Dict[str, Any] = Depends(get_current_admin_user)):
    return jinja_templates.TemplateResponse(
        request,
        "settings.html",
        {
            "authorized_emails": settings.authorized_emails_list,
            "user": user,
            "admin_user": True,
        },
    )

# ----------------- Web UI & Authentication -----------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
    return jinja_templates.TemplateResponse(request, "index.html", {"user": user, "admin_user": is_admin_user(user)})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None):
    user = request.session.get("user")
    if user:
        return RedirectResponse(url="/")

    google_enabled = bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)
    ms_enabled = bool(settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET)

    return jinja_templates.TemplateResponse(
        request,
        "login.html",
        {
            "google_enabled": google_enabled,
            "ms_enabled": ms_enabled,
            "error": error,
        },
    )

@app.get("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

@app.get("/auth/{provider}")
async def oauth_login(provider: str, request: Request):
    if provider not in ("google", "microsoft"):
        raise HTTPException(status_code=400, detail="Unsupported auth provider")

    client = getattr(oauth, provider, None)
    if not client:
        return RedirectResponse(url="/login?error=OAuth+provider+not+configured")

    redirect_path = (
        settings.GOOGLE_REDIRECT_PATH
        if provider == "google"
        else settings.MICROSOFT_REDIRECT_PATH
    )
    redirect_uri = build_redirect_uri(request, redirect_path)
    return await client.authorize_redirect(request, redirect_uri)

@app.get("/auth/{provider}/callback")
async def oauth_callback(provider: str, request: Request):
    client = getattr(oauth, provider, None)
    if not client:
        return RedirectResponse(url="/login?error=OAuth+provider+not+configured")

    try:
        token = await client.authorize_access_token(request)
        user_info = token.get("userinfo") or await client.userinfo(token=token)
        email = (user_info.get("email") or "").strip().lower()

        if not is_email_authorized(email):
            logger.warning(f"Unauthorized login attempt with email: {email}")
            return RedirectResponse(url="/login?error=Access+Denied:+Email+not+in+whitelist")

        request.session["user"] = {
            "email": email,
            "name": user_info.get("name", email.split("@")[0]),
            "provider": provider
        }
        return RedirectResponse(url="/")
    except Exception as e:
        logger.error(f"OAuth error: {e}")
        return RedirectResponse(url=f"/login?error=Authentication+failed:+{str(e)}")

@app.post("/auth/dev-login")
async def dev_login(request: Request, email: str = Form(...)):
    # Local fallback login when OAuth credentials are not set
    if not is_email_authorized(email):
        return RedirectResponse(url="/login?error=Access+Denied:+Email+not+in+whitelist", status_code=status.HTTP_303_SEE_OTHER)

    normalized_email = email.strip().lower()
    request.session["user"] = {
        "email": normalized_email,
        "name": normalized_email.split("@")[0],
        "provider": "dev"
    }
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

# ----------------- Agent REST APIs -----------------

@app.post("/api/chat")
async def chat_endpoint(request: Request):
    user = await get_current_user(request)
    body = await request.json()
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Empty message")

    session_id = f"web_{user['email']}"
    synthesize_voice = bool(body.get("synthesize_voice", False))

    async def event_stream():
        final_result: Dict[str, Any] = {}
        try:
            async for event in zeno_agent.stream_query(session_id, message):
                if event.get("type") == "delta":
                    yield sse_frame("delta", event)
                elif event.get("type") == "done":
                    final_result = event
                    audio_url = None
                    if synthesize_voice:
                        audio_path = AUDIO_CACHE_DIR / f"{uuid.uuid4().hex}{tts_engine.output_suffix}"
                        try:
                            saved_path = tts_engine.synthesize_to_file(final_result.get("response", ""), audio_path)
                            if saved_path and saved_path.exists():
                                audio_url = f"/api/audio/{saved_path.name}"
                        except Exception as e:
                            logger.warning(f"Voice synthesis error: {e}")

                    payload = dict(final_result)
                    payload["audio_url"] = audio_url
                    yield sse_frame("done", payload)
                else:
                    yield sse_frame(event.get("type", "message"), event)
        except Exception as e:
            logger.error(f"Chat streaming failed: {e}")
            yield sse_frame("error", {"detail": "Chat streaming failed"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.post("/api/voice")
async def voice_endpoint(
    request: Request,
    file: UploadFile = File(...),
    synthesize_voice: bool = Form(True),
):
    user = await get_current_user(request)
    session_id = f"web_{user['email']}"

    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    # 1. Transcribe voice input
    try:
        suffix = Path(file.filename or "voice.webm").suffix or ".webm"
        transcription = stt_engine.transcribe_bytes(audio_bytes, suffix=suffix)
    except Exception as e:
        logger.error(f"Voice transcription failed: {e}")
        raise HTTPException(status_code=500, detail="Speech-to-text failed")

    if not transcription:
        async def no_speech_stream():
            yield sse_frame("transcription", {"transcription": ""})
            yield sse_frame("done", {
                "transcription": "",
                "response": "I couldn't hear any speech. Please try speaking again.",
                "audio_url": None,
                "status": "success",
            })

        return StreamingResponse(
            no_speech_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def event_stream():
        yield sse_frame("transcription", {"transcription": transcription})
        try:
            async for event in zeno_agent.stream_query(session_id, transcription):
                if event.get("type") == "delta":
                    yield sse_frame("delta", event)
                elif event.get("type") == "done":
                    audio_url = None
                    if synthesize_voice:
                        audio_path = AUDIO_CACHE_DIR / f"{uuid.uuid4().hex}{tts_engine.output_suffix}"
                        try:
                            saved_path = tts_engine.synthesize_to_file(event.get("response", ""), audio_path)
                            if saved_path and saved_path.exists():
                                audio_url = f"/api/audio/{saved_path.name}"
                        except Exception as e:
                            logger.warning(f"Voice synthesis error: {e}")

                    payload = dict(event)
                    payload["transcription"] = transcription
                    payload["audio_url"] = audio_url
                    yield sse_frame("done", payload)
                else:
                    yield sse_frame(event.get("type", "message"), event)
        except Exception as e:
            logger.error(f"Voice streaming failed: {e}")
            yield sse_frame("error", {"detail": "Voice streaming failed"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.get("/api/audio/{filename}")
async def get_audio_file(filename: str):
    # Sanitize filename
    safe_name = Path(filename).name
    file_path = AUDIO_CACHE_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio not found or expired")
    media_type = "audio/mpeg" if file_path.suffix.lower() == ".mp3" else "audio/wav"
    return FileResponse(path=str(file_path), media_type=media_type)

@app.post("/api/clear")
async def clear_session_endpoint(request: Request):
    user = await get_current_user(request)
    session_id = f"web_{user['email']}"
    memory_store.clear_history(session_id)
    return {"status": "success", "message": "History cleared"}
