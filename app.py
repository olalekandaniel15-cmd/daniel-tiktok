import os, sqlite3, uuid, json
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "daniel_tiktok_v2.db")
UPLOADS = os.path.join(BASE, "static", "uploads")
os.makedirs(UPLOADS, exist_ok=True)
ALLOWED = {"mp4", "webm", "mov", "m4v"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "replace-with-a-long-random-secret")
app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024

# Owner payout destination: set these as private server environment variables.
# Never render these values on public pages or expose them in client-side JavaScript.
OWNER_PAYOUT_PROVIDER = os.environ.get("OWNER_PAYOUT_PROVIDER", "OPay")
OWNER_PAYOUT_ACCOUNT_NUMBER = os.environ.get("OWNER_PAYOUT_ACCOUNT_NUMBER", "")
OWNER_PAYOUT_ACCOUNT_NAME = os.environ.get("OWNER_PAYOUT_ACCOUNT_NAME", "")

def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def now():
    return datetime.utcnow().isoformat()

def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
          email TEXT UNIQUE NOT NULL, phone TEXT NOT NULL, password_hash TEXT NOT NULL,
          bio TEXT DEFAULT '', is_premium INTEGER DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS videos(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          caption TEXT NOT NULL, filename TEXT NOT NULL, created_at TEXT NOT NULL,
          views INTEGER DEFAULT 0, is_public INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS likes(
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
          PRIMARY KEY(user_id,video_id)
        );
        CREATE TABLE IF NOT EXISTS comments(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE, body TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS follows(
          follower_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          followed_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          PRIMARY KEY(follower_id,followed_id), CHECK(follower_id != followed_id)
        );
        CREATE TABLE IF NOT EXISTS notifications(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL, kind TEXT NOT NULL,
          message TEXT NOT NULL, target_id INTEGER, is_read INTEGER DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages(
          id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          receiver_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          body TEXT NOT NULL, created_at TEXT NOT NULL, is_read INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS gifts(
          id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER NOT NULL REFERENCES users(id),
          creator_id INTEGER NOT NULL REFERENCES users(id), video_id INTEGER REFERENCES videos(id),
          gift_name TEXT NOT NULL, amount_kobo INTEGER NOT NULL, owner_share_kobo INTEGER NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
          kind TEXT NOT NULL, amount_kobo INTEGER NOT NULL, reference TEXT UNIQUE NOT NULL,
          status TEXT DEFAULT 'pending', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ad_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
          event_type TEXT NOT NULL, campaign_code TEXT, consented INTEGER DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS call_signals(
          id INTEGER PRIMARY KEY AUTOINCREMENT, from_user INTEGER NOT NULL REFERENCES users(id),
          to_user INTEGER NOT NULL REFERENCES users(id), signal_type TEXT NOT NULL,
          payload TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)

def auth(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        if not session.get("uid"):
            flash("Please log in first.", "error")
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapped

def notify(user_id, actor_id, kind, message, target_id=None):
    with conn() as c:
        c.execute("INSERT INTO notifications(user_id,actor_id,kind,message,target_id,created_at) VALUES(?,?,?,?,?,?)",
                  (user_id, actor_id, kind, message, target_id, now()))

@app.context_processor
def context():
    user = None
    unread = 0
    if session.get("uid"):
        with conn() as c:
            user = c.execute("SELECT id,username,email,phone,is_premium FROM users WHERE id=?",
                             (session["uid"],)).fetchone()
            unread = c.execute("SELECT COUNT(*) n FROM notifications WHERE user_id=? AND is_read=0",
                               (session["uid"],)).fetchone()["n"]
    return {"current_user": user, "unread_notifications": unread}

@app.route("/")
def home():
    uid = session.get("uid", -1)
    with conn() as c:
        # Lightweight ranking: recent posts, engagement and followed creators.
        videos = c.execute("""
          SELECT v.*,u.username,
          (SELECT COUNT(*) FROM likes l WHERE l.video_id=v.id) likes_count,
          (SELECT COUNT(*) FROM comments cm WHERE cm.video_id=v.id) comments_count,
          (SELECT COUNT(*) FROM likes l WHERE l.video_id=v.id AND l.user_id=?) liked,
          EXISTS(SELECT 1 FROM follows f WHERE f.follower_id=? AND f.followed_id=v.user_id) following
          FROM videos v JOIN users u ON u.id=v.user_id WHERE v.is_public=1
          ORDER BY ((SELECT COUNT(*) FROM likes l WHERE l.video_id=v.id)*3 +
                    (SELECT COUNT(*) FROM comments cm WHERE cm.video_id=v.id)*2 +
                    CASE WHEN EXISTS(SELECT 1 FROM follows f WHERE f.follower_id=? AND f.followed_id=v.user_id) THEN 8 ELSE 0 END
                   ) DESC, v.id DESC LIMIT 80
        """, (uid,uid,uid)).fetchall()
    return render_template("home.html", videos=videos)

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username=request.form.get("username","").strip().lstrip("@")
        email=request.form.get("email","").strip().lower()
        phone=request.form.get("phone","").strip()
        password=request.form.get("password","")
        if not username or not email or not phone or len(password)<8:
            flash("Fill every field. Password must be at least 8 characters.", "error")
        else:
            try:
                with conn() as c:
                    cur=c.execute("INSERT INTO users(username,email,phone,password_hash,created_at) VALUES(?,?,?,?,?)",
                                  (username,email,phone,generate_password_hash(password),now()))
                    session["uid"]=cur.lastrowid
                return redirect(url_for("home"))
            except sqlite3.IntegrityError:
                flash("Username or email already exists.", "error")
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        ident=request.form.get("identity","").strip()
        with conn() as c:
            u=c.execute("SELECT * FROM users WHERE email=? OR username=? OR phone=?",
                         (ident.lower(),ident,ident)).fetchone()
        if u and check_password_hash(u["password_hash"],request.form.get("password","")):
            session["uid"]=u["id"]
            return redirect(url_for("home"))
        flash("Invalid login details.", "error")
    return render_template("login.html")

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/upload",methods=["GET","POST"])
@auth
def upload():
    if request.method=="POST":
        f=request.files.get("video"); caption=request.form.get("caption","").strip()
        ext=f.filename.rsplit(".",1)[-1].lower() if f and "." in f.filename else ""
        if not f or not f.filename or not caption:
            flash("Select a video and add a caption.","error")
        elif ext not in ALLOWED:
            flash("Use MP4, WEBM, MOV or M4V.","error")
        else:
            name=uuid.uuid4().hex+"."+ext
            f.save(os.path.join(UPLOADS,name))
            with conn() as c:
                c.execute("INSERT INTO videos(user_id,caption,filename,created_at) VALUES(?,?,?,?)",
                          (session["uid"],caption[:500],name,now()))
            flash("Video published.","success")
            return redirect(url_for("home"))
    return render_template("upload.html")

@app.post("/view/<int:vid>")
def view(vid):
    with conn() as c:
        c.execute("UPDATE videos SET views=views+1 WHERE id=?",(vid,))
    return ("",204)

@app.post("/like/<int:vid>")
@auth
def like(vid):
    with conn() as c:
        v=c.execute("SELECT user_id FROM videos WHERE id=?",(vid,)).fetchone()
        if not v: return ("Not found",404)
        old=c.execute("SELECT 1 FROM likes WHERE user_id=? AND video_id=?",(session["uid"],vid)).fetchone()
        if old: c.execute("DELETE FROM likes WHERE user_id=? AND video_id=?",(session["uid"],vid))
        else:
            c.execute("INSERT OR IGNORE INTO likes(user_id,video_id) VALUES(?,?)",(session["uid"],vid))
            if v["user_id"] != session["uid"]:
                c.execute("INSERT INTO notifications(user_id,actor_id,kind,message,target_id,created_at) VALUES(?,?,?,?,?,?)",
                          (v["user_id"],session["uid"],"like","liked your video",vid,now()))
    return redirect(request.referrer or url_for("home"))

@app.post("/comment/<int:vid>")
@auth
def comment(vid):
    body=request.form.get("body","").strip()
    if body:
        with conn() as c:
            v=c.execute("SELECT user_id FROM videos WHERE id=?",(vid,)).fetchone()
            if not v: return ("Not found",404)
            c.execute("INSERT INTO comments(user_id,video_id,body,created_at) VALUES(?,?,?,?)",
                      (session["uid"],vid,body[:500],now()))
            if v["user_id"] != session["uid"]:
                c.execute("INSERT INTO notifications(user_id,actor_id,kind,message,target_id,created_at) VALUES(?,?,?,?,?,?)",
                          (v["user_id"],session["uid"],"comment","commented on your video",vid,now()))
    return redirect(request.referrer or url_for("home"))

@app.post("/follow/<int:uid>")
@auth
def follow(uid):
    if uid==session["uid"]: return redirect(url_for("profile",uid=uid))
    with conn() as c:
        exists=c.execute("SELECT 1 FROM follows WHERE follower_id=? AND followed_id=?",(session["uid"],uid)).fetchone()
        if exists: c.execute("DELETE FROM follows WHERE follower_id=? AND followed_id=?",(session["uid"],uid))
        else:
            c.execute("INSERT OR IGNORE INTO follows(follower_id,followed_id) VALUES(?,?)",(session["uid"],uid))
            c.execute("INSERT INTO notifications(user_id,actor_id,kind,message,created_at) VALUES(?,?,?,?,?)",
                      (uid,session["uid"],"follow","started following you",now()))
    return redirect(request.referrer or url_for("home"))

@app.route("/profile/<int:uid>")
@auth
def profile(uid):
    with conn() as c:
        u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
        if not u: return ("User not found",404)
        videos=c.execute("SELECT * FROM videos WHERE user_id=? ORDER BY id DESC",(uid,)).fetchall()
        followers=c.execute("SELECT COUNT(*) n FROM follows WHERE followed_id=?",(uid,)).fetchone()["n"]
        following=c.execute("SELECT COUNT(*) n FROM follows WHERE follower_id=?",(uid,)).fetchone()["n"]
        is_following=c.execute("SELECT 1 FROM follows WHERE follower_id=? AND followed_id=?",
                               (session["uid"],uid)).fetchone() is not None
    return render_template("profile.html",profile_user=u,videos=videos,followers=followers,following=following,is_following=is_following)

@app.route("/inbox")
@auth
def inbox():
    with conn() as c:
        people=c.execute("""
          SELECT DISTINCT u.id,u.username FROM users u
          JOIN messages m ON (m.sender_id=u.id AND m.receiver_id=?) OR (m.receiver_id=u.id AND m.sender_id=?)
          WHERE u.id != ? ORDER BY u.username
        """,(session["uid"],session["uid"],session["uid"])).fetchall()
        users=c.execute("SELECT id,username FROM users WHERE id != ? ORDER BY username",(session["uid"],)).fetchall()
    return render_template("inbox.html",people=people,users=users)

@app.route("/messages/<int:uid>",methods=["GET","POST"])
@auth
def messages(uid):
    with conn() as c:
        other=c.execute("SELECT id,username FROM users WHERE id=?",(uid,)).fetchone()
        if not other: return ("User not found",404)
        if request.method=="POST":
            body=request.form.get("body","").strip()
            if body:
                c.execute("INSERT INTO messages(sender_id,receiver_id,body,created_at) VALUES(?,?,?,?)",
                          (session["uid"],uid,body[:2000],now()))
                c.execute("INSERT INTO notifications(user_id,actor_id,kind,message,created_at) VALUES(?,?,?,?,?)",
                          (uid,session["uid"],"message","sent you a message",now()))
                return redirect(url_for("messages",uid=uid))
        c.execute("UPDATE messages SET is_read=1 WHERE sender_id=? AND receiver_id=?",(uid,session["uid"]))
        thread=c.execute("""SELECT m.*,u.username FROM messages m JOIN users u ON u.id=m.sender_id
          WHERE (m.sender_id=? AND m.receiver_id=?) OR (m.sender_id=? AND m.receiver_id=?)
          ORDER BY m.id""",(session["uid"],uid,uid,session["uid"])).fetchall()
    return render_template("messages.html",other=other,thread=thread)

@app.get("/notifications")
@auth
def notifications():
    with conn() as c:
        rows=c.execute("SELECT n.*,u.username FROM notifications n LEFT JOIN users u ON u.id=n.actor_id WHERE n.user_id=? ORDER BY n.id DESC LIMIT 100",
                       (session["uid"],)).fetchall()
        c.execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(session["uid"],))
    return render_template("notifications.html",rows=rows)

@app.route("/live")
@auth
def live():
    return render_template("live.html")

@app.get("/dashboard")
@auth
def dashboard():
    with conn() as c:
        stats=c.execute("""
          SELECT COUNT(*) videos, COALESCE(SUM(views),0) views,
          (SELECT COUNT(*) FROM follows WHERE followed_id=?) followers,
          (SELECT COUNT(*) FROM likes l JOIN videos v ON v.id=l.video_id WHERE v.user_id=?) likes
          FROM videos WHERE user_id=?
        """,(session["uid"],session["uid"],session["uid"])).fetchone()
        gifts=c.execute("SELECT COALESCE(SUM(owner_share_kobo),0) total FROM gifts WHERE creator_id=?",
                        (session["uid"],)).fetchone()["total"]
        platform=c.execute("SELECT COALESCE(SUM(amount_kobo),0) total FROM gifts").fetchone()["total"]
    return render_template("dashboard.html",stats=stats,gifts=gifts,platform=platform)

@app.post("/gift/<int:uid>")
@auth
def gift(uid):
    # Demo ledger only. Production must verify real Paystack/Flutterwave webhooks.
    try: amount=int(request.form.get("amount",0))
    except ValueError: amount=0
    if amount not in (10000,20000,50000,100000):
        flash("Choose one of the available demo gifts.","error")
        return redirect(request.referrer or url_for("home"))
    owner_share=int(amount*0.20)  # demo owner commission; creator gets remaining 80%
    with conn() as c:
        c.execute("INSERT INTO gifts(sender_id,creator_id,gift_name,amount_kobo,owner_share_kobo,created_at) VALUES(?,?,?,?,?,?)",
                  (session["uid"],uid,"Virtual gift",amount,owner_share,now()))
    flash("Demo gift recorded. No real money was charged.","success")
    return redirect(request.referrer or url_for("home"))

@app.post("/ad-consent")
@auth
def ad_consent():
    consent=request.form.get("consent")=="yes"
    with conn() as c:
        c.execute("INSERT INTO ad_events(user_id,event_type,campaign_code,consented,created_at) VALUES(?,?,?,?,?)",
                  (session["uid"],"ad_personalization_choice","demo-campaign",int(consent),now()))
    flash("Your advertising preference has been saved.","success")
    return redirect(request.referrer or url_for("home"))

@app.route("/call/<int:uid>")
@auth
def call(uid):
    with conn() as c:
        other=c.execute("SELECT id,username FROM users WHERE id=?",(uid,)).fetchone()
    if not other: return ("User not found",404)
    return render_template("call.html",other=other)

@app.post("/api/call-signal/<int:uid>")
@auth
def call_signal(uid):
    data=request.get_json(silent=True) or {}
    kind=data.get("type","")
    if kind not in {"offer","answer","candidate","hangup"}: return jsonify(error="Invalid signal"),400
    payload=json.dumps(data.get("payload",{}))[:12000]
    with conn() as c:
        c.execute("INSERT INTO call_signals(from_user,to_user,signal_type,payload,created_at) VALUES(?,?,?,?,?)",
                  (session["uid"],uid,kind,payload,now()))
    return jsonify(ok=True)

@app.get("/api/call-signals")
@auth
def get_call_signals():
    with conn() as c:
        rows=c.execute("SELECT id,from_user,signal_type,payload FROM call_signals WHERE to_user=? ORDER BY id",
                       (session["uid"],)).fetchall()
        ids=[r["id"] for r in rows]
        if ids:
            c.executemany("DELETE FROM call_signals WHERE id=?",[(i,) for i in ids])
    return jsonify([dict(r) for r in rows])

@app.errorhandler(413)
def too_big(e):
    flash("Upload exceeds 150 MB.","error")
    return redirect(url_for("upload"))

init_db()
if __name__=="__main__":
    app.run(debug=True)
