import os
import uuid
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Dict, Any
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException, status, Header, Depends, APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.security.auth import oauth, is_email_authorized, get_current_user
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
        "auth_provider": settings.AUTH_PROVIDER
    }

# ----------------- Web UI & Authentication -----------------

# ----------------- Admin API for model defaults -----------------
admin_router = APIRouter(prefix="/admin", tags=["admin"])

def verify_admin(token: str = Header(..., description="Admin token")):
    if token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token")

@admin_router.get("/models")
def list_models():
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
def get_defaults():
    return prefs.get_prefs()

@admin_router.post("/defaults")
def set_defaults(
    fast_model: str,
    reasoning_model: str,
    fallback_model: str,
    _: None = Depends(verify_admin),
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
def admin_usage(request: Request, _: None = Depends(verify_admin)):
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
async def settings_page(request: Request):
    return jinja_templates.TemplateResponse(
        request,
        "settings.html",
        {
            "admin_token": settings.ADMIN_TOKEN,
            "authorized_emails": settings.authorized_emails_list,
        },
    )

# ----------------- Web UI & Authentication -----------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
    return jinja_templates.TemplateResponse(request, "index.html", {"user": user})

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

@app.get("/auth/{provider}")
async def oauth_login(provider: str, request: Request):
    if provider not in ("google", "microsoft"):
        raise HTTPException(status_code=400, detail="Unsupported auth provider")

    client = getattr(oauth, provider, None)
    if not client:
        return RedirectResponse(url="/login?error=OAuth+provider+not+configured")

    # Use the current request host so the session cookie and OAuth callback
    # stay on the same origin. Hardcoding localhost here can trigger
    # Authlib's mismatching_state error when the app is accessed through a
    # different host, IP, or reverse proxy.
    redirect_uri = str(request.url_for("oauth_callback", provider=provider))
    return await client.authorize_redirect(request, redirect_uri)

@app.get("/auth/{provider}/callback")
async def oauth_callback(provider: str, request: Request):
    client = getattr(oauth, provider, None)
    if not client:
        return RedirectResponse(url="/login?error=OAuth+provider+not+configured")

    try:
        token = await client.authorize_access_token(request)
        user_info = token.get("userinfo") or await client.userinfo(token=token)
        email = user_info.get("email")

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

    request.session["user"] = {
        "email": email.strip().lower(),
        "name": email.split("@")[0],
        "provider": "dev"
    }
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

# ----------------- Agent REST APIs -----------------

@app.post("/api/chat")
async def chat_endpoint(request: Request):
    user = await get_current_user(request)
    body = await request.json()
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Empty message")

    session_id = f"web_{user['email']}"
    result = await zeno_agent.process_query(session_id, message)

    # Optional speech synthesis for web client
    audio_url = None
    if body.get("synthesize_voice", False):
        audio_id = f"{uuid.uuid4().hex}.wav"
        audio_path = AUDIO_CACHE_DIR / audio_id
        saved_path = tts_engine.synthesize_to_file(result.get("response", ""), audio_path)
        if saved_path and saved_path.exists():
            audio_url = f"/api/audio/{audio_id}"

    result["audio_url"] = audio_url
    return JSONResponse(result)

@app.post("/api/voice")
async def voice_endpoint(request: Request, file: UploadFile = File(...)):
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
        return JSONResponse({
            "transcription": "",
            "response": "I couldn't hear any speech. Please try speaking again.",
            "audio_url": None,
            "status": "success"
        })

    # 2. Process query with Hermes Agent
    result = await zeno_agent.process_query(session_id, transcription)
    reply_text = result.get("response", "")

    # 3. Synthesize voice reply
    audio_id = f"{uuid.uuid4().hex}.wav"
    audio_path = AUDIO_CACHE_DIR / audio_id
    audio_url = None

    try:
        saved_path = tts_engine.synthesize_to_file(reply_text, audio_path)
        if saved_path and saved_path.exists():
            audio_url = f"/api/audio/{audio_id}"
    except Exception as e:
        logger.warning(f"Voice synthesis error: {e}")

    return JSONResponse({
        "transcription": transcription,
        "response": reply_text,
        "model_used": result.get("model_used"),
        "tools_called": result.get("tools_called"),
        "complexity": result.get("complexity"),
        "audio_url": audio_url,
        "status": "success"
    })

@app.get("/api/audio/{filename}")
async def get_audio_file(filename: str):
    # Sanitize filename
    safe_name = Path(filename).name
    file_path = AUDIO_CACHE_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio not found or expired")
    return FileResponse(path=str(file_path), media_type="audio/wav")

@app.post("/api/clear")
async def clear_session_endpoint(request: Request):
    user = await get_current_user(request)
    session_id = f"web_{user['email']}"
    memory_store.clear_history(session_id)
    return {"status": "success", "message": "History cleared"}
