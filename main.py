# main.py
from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json, os, sqlite3, yaml
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="supersecret")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# === CONFIG ===
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)
    USER_CREDENTIALS = config.get("users", {})
    ADMIN_PASSWORD = config.get("admin_password", "admin123")

def get_db(user):
    os.makedirs("user_dbs", exist_ok=True)
    db_path = f"user_dbs/{user}.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            id INTEGER PRIMARY KEY,
            paragraph_id INTEGER
        )
    """)
    return conn

def load_paragraphs(user):
    path = f"app/data/test_{user[-1]}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
        request.session['user'] = username
        return RedirectResponse(url="/reader", status_code=302)
    elif username == "admin" and password == ADMIN_PASSWORD:
        request.session['admin'] = True
        return RedirectResponse(url="/admin", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})

@app.get("/reader", response_class=HTMLResponse)
def reader(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/", 302)

    db = get_db(user)
    cur = db.cursor()
    cur.execute("SELECT paragraph_id FROM progress ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    current_index = row[0] + 1 if row else 0
    paragraphs = load_paragraphs(user)

    if current_index >= len(paragraphs):
        return templates.TemplateResponse("reader.html", {"request": request, "done": True})

    current_para = paragraphs[current_index]
    sentences = [s.strip() for s in current_para['text'].split('.') if s.strip()]
    progress = int((current_index + 1) / len(paragraphs) * 100)

    return templates.TemplateResponse("reader.html", {
        "request": request,
        "paragraph": current_para,
        "sentences": sentences,
        "progress": progress,
        "done": False
    })

@app.post("/confirm")
def confirm_read(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/", 302)

    db = get_db(user)
    cur = db.cursor()
    cur.execute("SELECT paragraph_id FROM progress ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    next_index = row[0] + 1 if row else 0

    paragraphs = load_paragraphs(user)
    if next_index < len(paragraphs):
        pid = paragraphs[next_index]['id']
        cur.execute("INSERT INTO progress (paragraph_id) VALUES (?)", (next_index,))
        db.commit()

    return RedirectResponse("/reader", 302)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", 302)

# === Admin Dashboard ===
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse("/", 302)

    stats = []
    for user in USER_CREDENTIALS:
        db_path = f"user_dbs/{user}.db"
        if not os.path.exists(db_path):
            stats.append({"user": user, "count": 0, "total": "?", "done": False})
            continue
        db = sqlite3.connect(db_path)
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM progress")
        count = cur.fetchone()[0]
        try:
            paragraphs = load_paragraphs(user)
            total = len(paragraphs)
            done = count >= total
        except:
            total = "?"
            done = False
        stats.append({"user": user, "count": count, "total": total, "done": done})

    return templates.TemplateResponse("admin.html", {"request": request, "stats": stats})

@app.get("/download_db/{username}")
def download_db(username: str, request: Request):
    if not request.session.get("admin"):
        return Response("Forbidden", status_code=403)
    if username not in USER_CREDENTIALS:
        return {"error": "Invalid user"}
    db_path = f"user_dbs/{username}.db"
    if not os.path.exists(db_path):
        return {"error": "DB not found"}
    return FileResponse(db_path, filename=f"{username}.db")