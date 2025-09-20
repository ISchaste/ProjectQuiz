import os, json, random, datetime, bcrypt
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request, Query, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()
SECRET_KEY = os.getenv("secret_key", "fallback_key")

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

USER_FILE = "users.json"
CHAR_FILE = "characters.json"
GAME_STATE_FILE = "game_state.json"
COMMENTS_FILE = "comments.json"

if not os.path.exists(USER_FILE):
    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

if not os.path.exists(GAME_STATE_FILE):
    with open(GAME_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "emoji": {"char": None, "last_update": None},
            "splash": {"char": None, "last_update": None},
            "classic": {"char": None, "last_update": None}
        }, f)

if not os.path.exists(COMMENTS_FILE):
    with open(COMMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

with open(CHAR_FILE, encoding="utf-8") as f:
    CHARACTERS = json.load(f)


def save_users(users):
    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def load_users():
    with open(USER_FILE, encoding="utf-8") as f:
        return json.load(f)

def get_current_user(request: Request):
    return request.session.get("username")

def require_login(request: Request):
    if not request.session.get("username"):
        raise RedirectResponse("/login", status_code=302)
    return request.session.get("username")

def load_game_state():
    with open(GAME_STATE_FILE, encoding="utf-8") as f:
        return json.load(f)

def save_game_state(state):
    with open(GAME_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def get_daily_character(mode="classic"):
    state = load_game_state()
    today = datetime.date.today().isoformat()

    if state[mode]["last_update"] != today or not state[mode]["char"]:
        state[mode]["char"] = random.choice(CHARACTERS)
        state[mode]["last_update"] = today
        save_game_state(state)
        clear_comments()
    return state[mode]["char"]

def load_comments():
    with open(COMMENTS_FILE, encoding="utf-8") as f:
        return json.load(f)

def save_comments(data):
    with open(COMMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def clear_comments():
    save_comments([])

def ensure_progress(session):
    if "progress" not in session:
        session["progress"] = {}
    for mode in ["classic", "emoji", "splash"]:
        if mode not in session["progress"]:
            session["progress"][mode] = False


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        await websocket.send_text(json.dumps({"type": "history", "messages": load_comments()}))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_text(json.dumps(message))

manager = ConnectionManager()

@app.websocket("/ws/comments")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            comments = load_comments()
            comments.append(msg)
            save_comments(comments)
            await manager.broadcast({"type": "new_message", "message": msg})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/register", response_class=HTMLResponse)
async def register_get(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "error": None})

@app.post("/register", response_class=HTMLResponse)
async def register_post(request: Request, username: str = Form(...), password: str = Form(...)):
    users = load_users()
    if any(u["username"] == username for u in users):
        return templates.TemplateResponse("register.html", {"request": request, "error": "Пользователь уже существует"})
    hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    users.append({"username": username, "password": hashed_pw})
    save_users(users)
    return RedirectResponse("/login", status_code=302)

@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    users = load_users()
    user = next((u for u in users if u["username"] == username), None)
    if not user or not bcrypt.checkpw(password.encode(), user["password"].encode()):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Неверный логин или пароль"})
    request.session["username"] = username
    for mode in ["classic", "emoji", "splash"]:
        request.session[f"used_names_{mode}"] = []
    request.session["classic_history"] = []
    request.session["progress"] = {"classic": False, "emoji": False, "splash": False}
    return RedirectResponse("/", status_code=302)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    ensure_progress(request.session)
    user = get_current_user(request)
    return templates.TemplateResponse("home.html", {"request": request, "user": user, "progress": request.session.get("progress")})


@app.get("/search_characters")
async def search_characters(request: Request, query: str = Query(""), mode: str = Query("classic")):
    used = request.session.get(f"used_names_{mode}", [])
    if not query.strip():
        results = [{"name": c["name_ru"], "avatar": c["avatar_url"]} for c in CHARACTERS if c["name_ru"] not in used]
    else:
        results = [
            {"name": c["name_ru"], "avatar": c["avatar_url"]}
            for c in CHARACTERS if c["name_ru"].lower().startswith(query.lower()) and c["name_ru"] not in used
        ]
    return JSONResponse(content=results[:50])


@app.get("/emoji", response_class=HTMLResponse)
async def emoji_get(request: Request, user: str = Depends(require_login)):
    ensure_progress(request.session)
    char = get_daily_character()
    return templates.TemplateResponse("emoji.html", {
        "request": request, "emojis": char["emoji_set"], "answer": char["name_ru"], "step": 1,
        "user": user, "progress": request.session["progress"], "done": request.session["progress"]["emoji"]
    })

@app.post("/emoji", response_class=HTMLResponse)
async def emoji_post(request: Request, guess: str = Form(...), answer: str = Form(...),
                     emojis: str = Form(...), step: int = Form(...), user: str = Depends(require_login)):
    ensure_progress(request.session)
    emojis_list = emojis.split(",")
    correct = guess.strip().lower() == answer.strip().lower()
    if not correct:
        used = request.session.get("used_names_emoji", [])
        if guess not in used:
            used.append(guess)
            request.session["used_names_emoji"] = used
    else:
        request.session["progress"]["emoji"] = True
    return templates.TemplateResponse("emoji.html", {
        "request": request, "emojis": emojis_list, "answer": answer, "guess": guess,
        "correct": correct, "step": step + (0 if correct else 1), "user": user,
        "progress": request.session["progress"], "done": request.session["progress"]["emoji"]
    })


# ----------------- Splash -----------------
@app.get("/splash", response_class=HTMLResponse)
async def splash_get(request: Request, user: str = Depends(require_login)):
    ensure_progress(request.session)
    char = get_daily_character()
    return templates.TemplateResponse("splash.html", {
        "request": request, "splash": char["splash_img_url"], "answer": char["name_ru"], "zoom": 350,
        "offset_x": random.randint(0, 50), "offset_y": random.randint(0, 50),
        "user": user, "progress": request.session["progress"], "done": request.session["progress"]["splash"]
    })

@app.post("/splash", response_class=HTMLResponse)
async def splash_post(request: Request, guess: str = Form(...), answer: str = Form(...),
                      splash: str = Form(...), zoom: int = Form(...),
                      offset_x: int = Form(...), offset_y: int = Form(...),
                      user: str = Depends(require_login)):
    ensure_progress(request.session)
    correct = guess.strip().lower() == answer.strip().lower()
    if not correct:
        used = request.session.get("used_names_splash", [])
        if guess not in used:
            used.append(guess)
            request.session["used_names_splash"] = used
        zoom = max(100, zoom - 50)
    else:
        request.session["progress"]["splash"] = True
    return templates.TemplateResponse("splash.html", {
        "request": request, "splash": splash, "answer": answer, "guess": guess,
        "correct": correct, "zoom": zoom, "offset_x": offset_x, "offset_y": offset_y,
        "user": user, "progress": request.session["progress"], "done": request.session["progress"]["splash"]
    })


# ----------------- Classic -----------------
@app.get("/classic", response_class=HTMLResponse)
async def classic_get(request: Request, user: str = Depends(require_login)):
    ensure_progress(request.session)
    char = get_daily_character()
    history = request.session.get("classic_history", [])
    return templates.TemplateResponse("classic.html", {
        "request": request, "target": char, "history": history,
        "user": user, "progress": request.session["progress"], "done": request.session["progress"]["classic"]
    })

@app.post("/classic", response_class=HTMLResponse)
async def classic_post(request: Request, character: str = Form(...), user: str = Depends(require_login)):
    ensure_progress(request.session)
    char = get_daily_character()
    guess_char = next((c for c in CHARACTERS if c["name_ru"].lower() == character.strip().lower()), None)
    history = request.session.get("classic_history", [])
    if guess_char:
        result = {
            "name": guess_char["name_ru"],
            "avatar": guess_char["avatar_url"],
            "gender": guess_char["gender"],
            "gender_match": guess_char["gender"] == char["gender"],
            "path": guess_char["path"],
            "path_match": guess_char["path"] == char["path"],
            "element": guess_char["element"],
            "element_match": guess_char["element"] == char["element"],
            "rarity": str(guess_char["rarity"]),
            "rarity_match": guess_char["rarity"] == char["rarity"],
            "patch": guess_char["patch"],
            "patch_match": guess_char["patch"] == char["patch"]
        }
        history.append(result)
        request.session["classic_history"] = history
        if guess_char["name_ru"].lower() != char["name_ru"].lower():
            used = request.session.get("used_names_classic", [])
            if guess_char["name_ru"] not in used:
                used.append(guess_char["name_ru"])
                request.session["used_names_classic"] = used
        else:
            request.session["progress"]["classic"] = True
    return templates.TemplateResponse("classic.html", {
        "request": request, "target": char, "history": history,
        "user": user, "progress": request.session["progress"], "done": request.session["progress"]["classic"]
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",  # слушать на всех интерфейсах
        port=8080,       # можно поменять на свой порт
        reload=True      # авто-перезапуск при изменениях кода
    )