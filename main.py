# main.py
from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json, os, sqlite3, yaml
from starlette.middleware.sessions import SessionMiddleware
import spacy
import os
import ast
JUSTIFICATION_DATA_PATH = "app/data/justification_demo.json"
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="supersecret")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# === NLP Setup ===
nlp = spacy.load("en_core_web_sm")

# === CONFIG ===
USER_CREDENTIALS = ast.literal_eval(os.getenv("USER_CREDENTIALS_JSON", "{}"))
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

def get_db(user):
    os.makedirs("/data/user_dbs", exist_ok=True)
    db_path = f"/data/user_dbs/{user}.db"
    print(f"Opening DB at: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            id INTEGER PRIMARY KEY,
            paragraph_id INTEGER,
            selections TEXT,
            paragraph TEXT,
            duration REAL
        )
    """)
    return conn

def load_paragraphs(user):
    user_file_map = {
        "zhiling": "team_1.json",
        "user2": "team_1_reversed.json",
        "user3": "team_2.json",
        "user4": "team_2_reversed.json",
        "bangdong": "test_1.json",
        "zhengzhe": "test_2.json",
        "test3": "test_3.json",
        "test4": "test_4.json",
    }
    filename = user_file_map.get(user)
    if not filename:
        raise ValueError(f"No file mapping found for user: {user}")
    path = f"app/data/{filename}"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
        request.session['user'] = username
        return RedirectResponse(url="/stage_select", status_code=302)  # 修改跳转
    elif username == "admin" and password == ADMIN_PASSWORD:
        request.session['admin'] = True
        return RedirectResponse(url="/admin", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})

@app.get("/stage_select", response_class=HTMLResponse)
def stage_select(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/", 302)

    # 定义专家用户名单
    expert_users = {"bangdong", "zhengzhe"}

    if user in expert_users:
        stages = [("Expert Arbitration", 4)]
    else:
        stages = [
            ("Initial Annotation", 1),
            ("Justification", 2),
            ("Discussion", 3),
        ]

    return templates.TemplateResponse("stage_select.html", {
        "request": request,
        "user": user,
        "stages": stages
    })

@app.get("/go_to_stage")
def go_to_stage(request: Request, stage: int):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/", 302)

    expert_users = {"expert1", "admin"}

    if stage == 1 and user not in expert_users:
        return RedirectResponse("/reader", 302)

    elif stage == 2 and user not in expert_users:
        if os.path.exists(JUSTIFICATION_DATA_PATH):  # ✅ 判断文件是否存在
            return RedirectResponse("/justification", 302)
        else:
            return templates.TemplateResponse("not_open.html", {"request": request, "stage": stage})

    elif stage == 4 and user in expert_users:
        return templates.TemplateResponse("not_open.html", {"request": request, "stage": stage})

    else:
        return templates.TemplateResponse("not_open.html", {"request": request, "stage": stage})

@app.get("/reader", response_class=HTMLResponse)
def reader(request: Request, stage: int = 1):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/", 302)

    db = get_db(user)
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM progress")
    row = cur.fetchone()
    current_index = row[0]
    paragraphs = load_paragraphs(user)

    if current_index >= len(paragraphs):
        return templates.TemplateResponse("reader.html", {"request": request, "done": True})

    current_para = paragraphs[current_index]
    doc = nlp(current_para['text'])
    sentences = [sent.text.strip() for sent in doc.sents]
    progress = int((current_index + 1) / len(paragraphs) * 100)

    return templates.TemplateResponse("reader.html", {
        "request": request,
        "paragraph": current_para,
        "sentences": sentences,
        "progress": progress,
        "current_index": current_index,
        "total": len(paragraphs),
        "done": False,
        "user": user
    })

@app.post("/confirm")
def confirm_read(request: Request, selection: str = Form(...), duration: float = Form(...)):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/", 302)

    db = get_db(user)
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM progress")
    row = cur.fetchone()
    next_index = row[0]

    paragraphs = load_paragraphs(user)
    if next_index < len(paragraphs):
        para_text = paragraphs[next_index]['text']
        real_para_id = paragraphs[next_index].get("id", next_index)
        cur.execute(
            "INSERT INTO progress (paragraph_id, selections, paragraph, duration) VALUES (?, ?, ?, ?)",
            (real_para_id, selection, para_text, duration)
        )
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
        db_path = f"/data/user_dbs/{user}.db"
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

@app.get("/justification", response_class=HTMLResponse)
def justification_page(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/", 302)

    # 加载模拟的justification数据
    with open("app/data/justification_demo.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    # 目前仅返回一个测试段落
    para = data[0]
    sentences = para["text"].split(". ")
    conflicts = []

    for s in sentences:
        s = s.strip()
        if s and s in para["sentence_labels"]:
            labels = para["sentence_labels"][s]
            if len(set(labels)) > 1:
                conflicts.append(s)

    return templates.TemplateResponse("justification.html", {
        "request": request,
        "paragraph": para["text"],
        "conflicts": conflicts
    })

@app.get("/download_db/{username}")
def download_db(username: str, request: Request):
    if not request.session.get("admin"):
        return Response("Forbidden", status_code=403)
    if username not in USER_CREDENTIALS:
        return {"error": "Invalid user"}
    db_path = f"/data/user_dbs/{username}.db"
    if not os.path.exists(db_path):
        return {"error": "DB not found"}
    return FileResponse(db_path, filename=f"{username}.db")

@app.get("/admin/reset_user/{username}")
def reset_user_db(username: str, request: Request):
    if not request.session.get("admin"):
        return Response("Forbidden", status_code=403)
    db_path = f"/data/user_dbs/{username}.db"
    if os.path.exists(db_path):
        os.remove(db_path)
        return {"status": f"Database for {username} has been deleted."}
    return {"status": f"Database for {username} not found."}

@app.get("/admin/reset_all")
def reset_all_dbs(request: Request):
    if not request.session.get("admin"):
        return Response("Forbidden", status_code=403)
    base_path = "/data/user_dbs"
    if not os.path.exists(base_path):
        return {"status": "No database directory found."}
    results = []
    for user in USER_CREDENTIALS:
        db_path = os.path.join(base_path, f"{user}.db")
        if os.path.exists(db_path):
            os.remove(db_path)
            results.append(f"Deleted {user}.db")
        else:
            results.append(f"{user}.db not found")
    return {"results": results}