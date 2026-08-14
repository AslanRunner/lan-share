import argparse
import io
import math
import random
import secrets
from datetime import datetime
from pathlib import Path
import socket
from typing import List, Optional

from fastapi import FastAPI, File, UploadFile, Request, Form, Depends, HTTPException, status
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer, BadSignature
import qrcode
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
import uvicorn

# Initialize rich console for terminal UI output
console = Console()

# FastAPI application instance
app = FastAPI(title="LAN Share Pro - Daily Python Edition")

# Base paths and directory setup inside daily_python folder
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Mount static files and initialize Jinja2 templates
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Global configurations set via CLI arguments
TARGET_DIR: Path = Path.home() / "lanshare"
PORT: int = 8000
HOST_IP: str = "127.0.0.1"

# Security & PIN Authentication globals
SERVER_PIN: str = f"{random.randint(1000, 9999)}"
SECRET_KEY: str = secrets.token_hex(16)
SESSION_COOKIE_NAME = "lanshare_session"
signer = URLSafeSerializer(SECRET_KEY)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".svg", ".avif", ".bmp"}


class AuthRequired(Exception):
    """Custom exception raised when a user is not authenticated."""
    pass


@app.exception_handler(AuthRequired)
async def auth_required_handler(request: Request, exc: AuthRequired):
    """Redirects unauthenticated users to the PIN login page."""
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


def make_session_cookie() -> str:
    """Creates a cryptographically signed session cookie payload."""
    return signer.dumps({"auth": True})


def is_authenticated(request: Request) -> bool:
    """Verifies whether the request carries a valid signed session cookie."""
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie:
        return False
    try:
        data = signer.loads(cookie)
        return data.get("auth") is True
    except BadSignature:
        return False


def require_auth(request: Request):
    """FastAPI dependency enforcing PIN authentication."""
    if not is_authenticated(request):
        raise AuthRequired()


def get_lan_ip() -> str:
    """Finds the host's actual local area network (LAN) IP address using a UDP socket."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def unique_path(folder: Path, name: str) -> Path:
    """Prevents file collisions by adding numerical suffixes if a file exists."""
    safe_name = Path(name).name
    p = folder / safe_name
    if not p.exists():
        return p

    stem = p.stem
    suffix = p.suffix

    for i in range(1, 10000):
        candidate = folder / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return folder / f"{stem}-{timestamp}{suffix}"


def resolve_upload_path(folder: Path, name: str) -> Optional[Path]:
    """
    Defense-in-depth path traversal check.
    Ensures the target file strictly resides within the allowed upload folder.
    """
    safe_name = Path(name).name
    candidate = (folder / safe_name).resolve()
    folder_resolved = folder.resolve()
    try:
        candidate.relative_to(folder_resolved)
    except ValueError:
        return None

    if not candidate.is_file():
        return None
    return candidate


def format_bytes(size: int) -> str:
    """Formats file size into human readable string."""
    if size == 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size, 1024)))
    p = math.pow(1024, i)
    s = round(size / p, 1)
    return f"{s} {size_name[i]}"



# FASTAPI ROUTE HANDLERS
@app.get("/login")
async def login_page(request: Request, error: str = ""):
    """Renders the PIN unlock template with modern Starlette signature."""
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": error},
    )


@app.post("/login")
async def process_login(request: Request, pin: str = Form(...)):
    """Validates submitted PIN and sets signed session cookie on success."""
    if pin.strip() == SERVER_PIN:
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=make_session_cookie(),
            httponly=True,
            samesite="lax",
        )
        return response
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "Invalid PIN. Check host terminal."},
        status_code=401,
    )


@app.get("/")
async def index(request: Request, _: None = Depends(require_auth)):
    """Renders the main dashboard template with upload dropzone and file gallery."""
    raw_files = sorted(
        [p for p in TARGET_DIR.iterdir() if p.is_file() and not p.name.startswith(".")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    files_data = []
    for f in raw_files:
        files_data.append({
            "name": f.name,
            "size_str": format_bytes(f.stat().st_size),
            "mtime_str": datetime.fromtimestamp(f.stat().st_mtime).strftime("%b %d, %H:%M"),
            "is_image": f.suffix.lower() in IMAGE_EXTENSIONS,
        })

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "host_ip": HOST_IP,
            "port": PORT,
            "files": files_data,
        },
    )


@app.post("/upload")
async def upload_files(files: List[UploadFile] = File(...), _: None = Depends(require_auth)):
    """Handles async file upload with 1 MB streaming chunks."""
    saved_names = []
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    for file in files:
        if not file.filename:
            continue

        filename = Path(file.filename).name
        target_path = unique_path(TARGET_DIR, filename)

        with open(target_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)

        saved_names.append(target_path.name)
        console.print(f"[bold green]✓ Saved:[/bold green] {target_path.name} -> [dim]{target_path}[/dim]")

    return JSONResponse({"ok": True, "saved": saved_names})


@app.get("/files/{filename}")
async def download_file(filename: str, _: None = Depends(require_auth)):
    """Serves file downloads with defense-in-depth path traversal checks."""
    safe_file = resolve_upload_path(TARGET_DIR, filename)
    if not safe_file:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=safe_file, filename=safe_file.name)


@app.post("/files/{filename}/delete")
async def delete_file(filename: str, _: None = Depends(require_auth)):
    """Deletes specified file from upload directory."""
    safe_file = resolve_upload_path(TARGET_DIR, filename)
    if not safe_file:
        raise HTTPException(status_code=404, detail="File not found")

    try:
        safe_file.unlink()
        console.print(f"[bold red]🗑️ Deleted:[/bold red] [dim]{safe_file.name}[/dim]")
        return JSONResponse({"ok": True})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def print_startup_banner(url: str, save_dir: Path, pin: str):
    """Prints rich terminal banner showing PIN, QR code, and URL."""
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)

    f = io.StringIO()
    qr.print_ascii(out=f, invert=True)
    qr_str = f.getvalue()

    panel_text = Text()
    panel_text.append("Open on any device on the same WiFi:\n\n", style="bold white")
    panel_text.append(f"  {url}\n\n", style="bold cyan link " + url)
    panel_text.append(f"🔒 PIN: ", style="bold white")
    panel_text.append(f"{pin}\n\n", style="bold yellow reverse")
    panel_text.append("Or scan the QR code below:\n\n", style="bold white")
    panel_text.append(qr_str + "\n")
    panel_text.append(f"Files land in: ", style="dim white")
    panel_text.append(f"{save_dir}\n", style="bold yellow")
    panel_text.append("Press Ctrl+C to stop.", style="dim italic")

    panel = Panel(
        panel_text,
        title="[bold cyan]📷 LAN Share Pro (Daily Python Edition)[/bold cyan]",
        subtitle="[dim]Two-Way Peer Transfer • Located in daily_python[/dim]",
        border_style="cyan",
        expand=False,
        padding=(1, 4),
    )

    console.print()
    console.print(panel)
    console.print()


def main():
    """CLI entry point."""
    global TARGET_DIR, PORT, HOST_IP

    parser = argparse.ArgumentParser(description="LAN File Sharing System - Daily Python Edition")
    parser.add_argument(
        "target",
        nargs="?",
        default=str(Path.home() / "lanshare"),
        help="Target folder to save uploaded files (default: ~/lanshare)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to run the server on (default: 8000)",
    )

    args = parser.parse_args()
    TARGET_DIR = Path(args.target).expanduser().resolve()
    PORT = args.port

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    HOST_IP = get_lan_ip()
    url = f"http://{HOST_IP}:{PORT}"

    print_startup_banner(url, TARGET_DIR, SERVER_PIN)

    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
