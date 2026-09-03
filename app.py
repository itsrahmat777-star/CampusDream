from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, jsonify
import sqlite3, hashlib, re, os, csv, io, uuid
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename
from PIL import Image as PILImage

from datetime import timedelta

app = Flask(__name__)
app.secret_key = 'dreamcampus-secret-2024'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
DATABASE = os.path.join(os.path.dirname(__file__), 'campus.db')

# ── File Upload Config ─────────────────────────────────────────
UPLOAD_FOLDER   = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
ALLOWED_EXT     = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}
MAX_FILE_MB     = 10          # max upload size in MB
MAX_IMG_WIDTH   = 1200        # resize if wider than this
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_MB * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

def save_uploaded_image(file_obj):
    """
    Saves an uploaded image to static/uploads/.
    - Validates extension
    - Resizes to max 1200px wide (keeps aspect ratio)
    - Converts to JPEG for consistency
    - Returns the public URL path  e.g. /static/uploads/abc123.jpg
    - Returns None on any error
    """
    if not file_obj or file_obj.filename == '':
        return None
    if not allowed_file(file_obj.filename):
        return None
    try:
        unique_name = uuid.uuid4().hex + '.jpg'
        save_path   = os.path.join(UPLOAD_FOLDER, unique_name)
        img = PILImage.open(file_obj)
        img = img.convert('RGB')          # handles PNG transparency → JPEG
        # Resize if too wide
        if img.width > MAX_IMG_WIDTH:
            ratio  = MAX_IMG_WIDTH / img.width
            new_h  = int(img.height * ratio)
            img    = img.resize((MAX_IMG_WIDTH, new_h), PILImage.LANCZOS)
        img.save(save_path, 'JPEG', quality=85, optimize=True)
        return '/static/uploads/' + unique_name
    except Exception as e:
        print(f'Image upload error: {e}')
        return None

# Fallback SVG images (shown when Unsplash CDN is unavailable)
from image_fallbacks import IMAGE_FALLBACKS

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def setup_db():
    """
    Creates all tables if they don't exist.
    NEVER deletes existing data — safe to call on every startup.
    """
    db = get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL, role TEXT DEFAULT 'student',
            bio TEXT DEFAULT '', points INTEGER DEFAULT 0,
            phone TEXT DEFAULT '',
            phone_verified INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, description TEXT,
            event_date TEXT, event_time TEXT, venue TEXT,
            max_participants INTEGER DEFAULT 50,
            category TEXT DEFAULT 'General', status TEXT DEFAULT 'upcoming',
            image_url TEXT DEFAULT '',
            fallback_image TEXT DEFAULT '',
            created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS registrations (
            user_id INTEGER, event_id INTEGER,
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP,
            attended INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, event_id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(event_id) REFERENCES events(id)
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, event_id INTEGER,
            rating INTEGER CHECK(rating BETWEEN 1 AND 5),
            comment TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, event_id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(event_id) REFERENCES events(id)
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL, receiver_id INTEGER,
            event_id INTEGER, subject TEXT NOT NULL, body TEXT NOT NULL,
            is_read INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(sender_id) REFERENCES users(id),
            FOREIGN KEY(receiver_id) REFERENCES users(id),
            FOREIGN KEY(event_id) REFERENCES events(id)
        );
        CREATE TABLE IF NOT EXISTS event_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL, title TEXT NOT NULL,
            description TEXT NOT NULL, proposed_date TEXT,
            proposed_time TEXT, venue TEXT,
            expected_participants INTEGER DEFAULT 50,
            category TEXT DEFAULT 'General', status TEXT DEFAULT 'pending',
            admin_note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TEXT,
            FOREIGN KEY(student_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS bookmarks (
            user_id INTEGER, event_id INTEGER,
            saved_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, event_id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(event_id) REFERENCES events(id)
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, message TEXT NOT NULL,
            link TEXT, is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    ''')

    # ── Seed only if DB is completely empty (first run ever) ──────────
    existing = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if existing > 0:
        db.close()
        return   # Data already exists — do NOT touch it

    # ── First-run seed data ───────────────────────────────────────────
    pa = hashlib.sha256(b'admin123').hexdigest()
    ps = hashlib.sha256(b'student123').hexdigest()
    users = [
        # (name, email, pw, role, bio, points, phone, phone_verified)
        ('Admin User','admin@dream.edu',pa,'admin','DreamCampus administrator.',0,'9000000001',1),
        ('Rahul Sharma','rahul@dream.edu',ps,'student','BCA Final Year | Tech enthusiast | Hyderabad',120,'9876543210',1),
        ('Priya Reddy','priya@dream.edu',ps,'student','BCA Final Year | Cultural events lover | Osmania University',95,'9823456781',1),
        ('Arjun Mehta','arjun@dream.edu',ps,'student','MCA Student | Sports & Hackathons | JNTUH',80,'9712345678',1),
        ('Sneha Patel','sneha@dream.edu',ps,'student','BCA | Photography & Arts | VNR VJIET',65,'9601234567',1),
    ]
    for u in users:
        db.execute("INSERT INTO users(name,email,password,role,bio,points,phone,phone_verified) VALUES(?,?,?,?,?,?,?,?)", u)

    # (title, desc, date, time, venue, max, cat, status, image_key)
    # image_key maps to IMAGE_FALLBACKS for offline fallback; Unsplash URL stored in DB
    events = [
        # ── Original 10 events ───────────────────────────────────────
        ('Hack the Future 2026',
         'A 48-hour hackathon for BCA/MCA/B.Tech students. Build innovative solutions. Top 3 teams win cash prizes and internship opportunities at top Hyderabad startups.',
         '2026-04-18','09:00','CBIT – Gandipet, Hyderabad',120,'Technical','upcoming',
         'https://images.unsplash.com/photo-1517694712202-14dd9538aa97?w=700&q=80',
         IMAGE_FALLBACKS['hack']),
        ('Starlight Cultural Fest',
         'Annual inter-college cultural event: classical dance, music, street plays, rangoli, art. Prizes worth ₹50,000.',
         '2026-04-25','17:00','Osmania University Auditorium, Amberpet',300,'Cultural','upcoming',
         'https://images.unsplash.com/photo-1492684223066-81342ee5ff30?w=700&q=80',
         IMAGE_FALLBACKS['cultural']),
        ('Tech Talk: AI & Careers',
         'Industry professionals from TCS, Infosys discuss AI career paths and trends for 2026 graduates. Networking session included.',
         '2026-03-20','14:00','JNTUH – Seminar Hall, Kukatpally',80,'Technical','completed',
         'https://images.unsplash.com/photo-1475721027785-f74eccf877e2?w=700&q=80',
         IMAGE_FALLBACKS['techtalk']),
        ('Inter-College Cricket Cup',
         '20-over tournament: CBIT, MGIT, JNTUH, Osmania, VNR VJIET. Winner gets ₹25,000 prize.',
         '2026-05-08','08:00','MGIT Sports Complex, Gandipet Road',200,'Sports','upcoming',
         'https://images.unsplash.com/photo-1531415074968-036ba1b575da?w=700&q=80',
         IMAGE_FALLBACKS['cricket']),
        ('Photography & Reels Contest',
         'Capture Hyderabad — Charminar, Hussain Sagar, campus life. Best entries win DJI equipment.',
         '2026-04-06','07:00','VNR VJIET – Main Campus, Bachupally',40,'Arts','upcoming',
         'https://images.unsplash.com/photo-1502982720700-bfff97f2ecac?w=700&q=80',
         IMAGE_FALLBACKS['photo']),
        ('Web Dev Bootcamp',
         'Two-day workshop: HTML, CSS, Flask, REST APIs, Render deployment. Certificates + placement assistance.',
         '2026-03-29','10:00','Vasavi College – Lab Block, Ibrahimbagh',60,'Technical','upcoming',
         'https://images.unsplash.com/photo-1461749280684-dccba630e2f6?w=700&q=80',
         IMAGE_FALLBACKS['webdev']),
        ('Freshers Orientation 2026',
         'Welcome event with campus tour, games, lucky draws, DJ night. Free dinner included.',
         '2026-06-20','18:00','CVR College – Main Auditorium, Ibrahimbagh',400,'Cultural','upcoming',
         'https://images.unsplash.com/photo-1523580494863-6f3031224c94?w=700&q=80',
         IMAGE_FALLBACKS['freshers']),
        ('Business Plan Competition',
         'Present your startup to T-Hub investors. Top ideas receive seed funding up to ₹5 lakhs.',
         '2026-05-15','10:00','T-Hub, IIIT Hyderabad, Gachibowli',100,'General','upcoming',
         'https://images.unsplash.com/photo-1559136555-9303baea8ebd?w=700&q=80',
         IMAGE_FALLBACKS['business']),
        ('Yoga & Wellness Day',
         'Inter-college yoga championship + mental wellness drive. Certified instructors from Hyderabad Yoga Association.',
         '2026-04-21','06:30','Osmania University Grounds, Amberpet',150,'Sports','upcoming',
         'https://images.unsplash.com/photo-1544367567-0f2fcb009e0b?w=700&q=80',
         IMAGE_FALLBACKS['yoga']),
        ('Urdu & Telugu Poetry Night',
         'Urdu mushaira and Telugu kavita sammelanam under the stars. Free entry + refreshments.',
         '2026-05-02','19:00','Ravindra Bharathi Auditorium, Nampally',200,'Cultural','upcoming',
         'https://images.unsplash.com/photo-1507838153414-b4b713384a76?w=700&q=80',
         IMAGE_FALLBACKS['poetry']),
        # ── 5 New Events ─────────────────────────────────────────────
        ('Robotics & IoT Expo 2026',
         'Showcase your robots and IoT projects! Competition across automation, smart systems, and embedded electronics. Top 3 teams win sponsored components worth ₹30,000.',
         '2026-05-20','10:00','CBIT – Innovation Lab, Gandipet, Hyderabad',80,'Technical','upcoming',
         'https://images.unsplash.com/photo-1485827404703-89b55fcc595e?w=700&q=80',
         IMAGE_FALLBACKS['robotics']),
        ('Inter-College Debate Championship',
         'Parliamentary-style debate tournament across 12 Hyderabad colleges. Topics: AI ethics, climate policy, education reform. Winner trophy + ₹15,000 prize.',
         '2026-04-30','10:00','Osmania University – Seminar Hall, Amberpet',120,'General','upcoming',
         'https://images.unsplash.com/photo-1524178232363-1fb2b075b655?w=700&q=80',
         IMAGE_FALLBACKS['debate']),

        ('Data Science & ML Hackathon',
         'Solve real-world problems using Python, pandas, scikit-learn, and ML pipelines. Datasets from Hyderabad Smart City initiative. Cloud credits and internship offers for winners.',
         '2026-06-05','09:00','IIIT Hyderabad – Research Block, Gachibowli',60,'Technical','upcoming',
         'https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=700&q=80',
         IMAGE_FALLBACKS['datascience']),
        ('Campus Marathon 2026',
         '5km and 10km categories open to all college students. Certificate of participation for all finishers. Top 3 in each category win medals and sports gear worth ₹10,000.',
         '2026-06-15','06:00','MGIT – Sports Ground, Gandipet Road, Hyderabad',250,'Sports','upcoming',
         'https://images.unsplash.com/photo-1552674605-db6ffd4facb5?w=700&q=80',
         IMAGE_FALLBACKS['marathon']),
    ]
    for e in events:
        db.execute("""INSERT INTO events(title,description,event_date,event_time,venue,
                      max_participants,category,status,image_url,fallback_image)
                      VALUES(?,?,?,?,?,?,?,?,?,?)""", e)

    regs = [(2,1),(2,2),(2,4),(2,6),(3,2),(3,5),(3,7),(3,10),(4,1),(4,4),(4,8),(4,9),(5,5),(5,7),(5,10),(2,11),(3,12),(4,13),(2,14),(3,11),(4,12)]
    for r in regs: db.execute("INSERT INTO registrations(user_id,event_id) VALUES(?,?)", r)
    attended = [(2,3),(3,3),(5,3)]
    for a in attended: db.execute("INSERT INTO registrations(user_id,event_id,attended) VALUES(?,?,1)", a)

    feedbacks = [
        (2,3,5,'Absolutely brilliant! The Infosys AI talk was eye-opening. Highly recommend to all CS students.'),
        (3,3,4,'Very informative and well-organised. Would have loved more Q&A time with the speakers.'),
        (5,3,5,'One of the best tech events I have attended. Great networking opportunities!'),
    ]
    for f in feedbacks:
        db.execute("INSERT INTO feedback(user_id,event_id,rating,comment) VALUES(?,?,?,?)", f)

    bms = [(2,8),(3,1),(4,2),(5,4),(2,11),(4,14),(5,12)]
    for b in bms: db.execute("INSERT INTO bookmarks(user_id,event_id) VALUES(?,?)", b)

    for uid in [2,3,4,5]:
        db.execute("INSERT INTO notifications(user_id,message,link) VALUES(?,?,?)",
                   (uid,'Welcome to DreamCampus! Browse events and earn points.','/events'))

    db.commit(); db.close()

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()
def valid_email(e): return re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', e)
def valid_phone(p):
    """Accept Indian mobile: 10 digits, starts with 6-9. Optional +91 or 0 prefix."""
    p = re.sub(r'[\s\-\(\)]', '', p)   # strip spaces, dashes, brackets
    p = re.sub(r'^(\+91|91|0)', '', p)    # strip country/trunk prefix
    return bool(re.match(r'^[6-9]\d{9}$', p))
def normalise_phone(p):
    """Return clean 10-digit phone or empty string."""
    p = re.sub(r'[\s\-\(\)]', '', p)
    p = re.sub(r'^(\+91|91|0)', '', p)
    return p if re.match(r'^[6-9]\d{9}$', p) else ''

def push_notif(db, user_id, message, link=None):
    db.execute("INSERT INTO notifications(user_id,message,link) VALUES(?,?,?)", (user_id, message, link))

def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if 'user_id' not in session:
            flash('Please login to continue.', 'info')
            return redirect(url_for('login'))
        return f(*a, **kw)
    return dec

def admin_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if session.get('role') != 'admin':
            flash('Admin access required.', 'error')
            return redirect(url_for('index'))
        return f(*a, **kw)
    return dec

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    db = get_db()
    events = db.execute("SELECT * FROM events WHERE status='upcoming' ORDER BY event_date ASC LIMIT 6").fetchall()
    stats  = {
        'events':   db.execute("SELECT COUNT(*) FROM events WHERE status='upcoming'").fetchone()[0],
        'students': db.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0],
        'regs':     db.execute("SELECT COUNT(*) FROM registrations").fetchone()[0],
    }
    next_event = db.execute("SELECT * FROM events WHERE status='upcoming' ORDER BY event_date ASC LIMIT 1").fetchone()
    db.close()
    return render_template('index.html', events=events, stats=stats, next_event=next_event)

@app.route('/events')
def events():
    db = get_db()
    search   = request.args.get('q','')
    category = request.args.get('category','All')
    sort     = request.args.get('sort','date')
    q = "SELECT * FROM events WHERE status='upcoming'"
    params = []
    if search:
        q += " AND (title LIKE ? OR description LIKE ? OR venue LIKE ?)"
        params += [f'%{search}%']*3
    if category != 'All':
        q += " AND category=?"
        params.append(category)
    q += " ORDER BY " + ("event_date ASC" if sort=='date' else "id DESC")
    evs = db.execute(q, params).fetchall()
    bookmarked = set()
    if 'user_id' in session:
        bms = db.execute("SELECT event_id FROM bookmarks WHERE user_id=?", (session['user_id'],)).fetchall()
        bookmarked = {b['event_id'] for b in bms}
    result = []
    for ev in evs:
        cnt = db.execute("SELECT COUNT(*) FROM registrations WHERE event_id=?", (ev['id'],)).fetchone()[0]
        avg = db.execute("SELECT ROUND(AVG(rating),1) FROM feedback WHERE event_id=?", (ev['id'],)).fetchone()[0]
        result.append({'ev':dict(ev),'count':cnt,'avg':avg,'bookmarked':ev['id'] in bookmarked})
    db.close()
    return render_template('events.html', events=result, search=search, category=category, sort=sort)

@app.route('/event/<int:eid>')
def event_detail(eid):
    db  = get_db()
    ev  = db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    if not ev: return redirect(url_for('events'))
    cnt = db.execute("SELECT COUNT(*) FROM registrations WHERE event_id=?", (eid,)).fetchone()[0]
    is_registered = already_reviewed = is_bookmarked = False
    if 'user_id' in session:
        uid = session['user_id']
        is_registered    = bool(db.execute("SELECT 1 FROM registrations WHERE user_id=? AND event_id=?", (uid,eid)).fetchone())
        already_reviewed = bool(db.execute("SELECT 1 FROM feedback WHERE user_id=? AND event_id=?", (uid,eid)).fetchone())
        is_bookmarked    = bool(db.execute("SELECT 1 FROM bookmarks WHERE user_id=? AND event_id=?", (uid,eid)).fetchone())
    feedbacks  = db.execute("SELECT f.*, u.name FROM feedback f JOIN users u ON f.user_id=u.id WHERE f.event_id=? ORDER BY f.created_at DESC", (eid,)).fetchall()
    avg_rating = db.execute("SELECT ROUND(AVG(rating),1) FROM feedback WHERE event_id=?", (eid,)).fetchone()[0]
    attendees  = db.execute("SELECT u.name FROM registrations r JOIN users u ON r.user_id=u.id WHERE r.event_id=? LIMIT 10", (eid,)).fetchall()
    db.close()
    return render_template('event_detail.html', ev=dict(ev), count=cnt,
                           is_registered=is_registered, already_reviewed=already_reviewed,
                           is_bookmarked=is_bookmarked, feedbacks=feedbacks,
                           avg_rating=avg_rating, attendees=attendees)

@app.route('/register_event/<int:eid>', methods=['POST'])
@login_required
def register_event(eid):
    # Require verified phone before registering
    db_chk = get_db()
    user_phone = db_chk.execute("SELECT phone FROM users WHERE id=?", (session['user_id'],)).fetchone()['phone']
    db_chk.close()
    if not user_phone:
        flash('⚠️ Please add your mobile number in your Profile before registering for events.', 'error')
        return redirect(url_for('profile'))
    db  = get_db()
    ev  = db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    cnt = db.execute("SELECT COUNT(*) FROM registrations WHERE event_id=?", (eid,)).fetchone()[0]
    if cnt >= ev['max_participants']:
        flash('Event is fully booked!', 'error')
    else:
        try:
            db.execute("INSERT INTO registrations(user_id,event_id) VALUES(?,?)", (session['user_id'],eid))
            db.execute("UPDATE users SET points=points+10 WHERE id=?", (session['user_id'],))
            push_notif(db, session['user_id'], f'Registered for "{ev["title"]}"! +10 points 🎉', f'/event/{eid}')
            db.commit()
            flash(f'Registered for {ev["title"]}! +10 points earned 🎉', 'success')
        except sqlite3.IntegrityError: flash('Already registered!', 'info')
    db.close()
    return redirect(url_for('event_detail', eid=eid))

@app.route('/cancel_event/<int:eid>', methods=['POST'])
@login_required
def cancel_event(eid):
    db = get_db()
    db.execute("DELETE FROM registrations WHERE user_id=? AND event_id=?", (session['user_id'],eid))
    db.execute("UPDATE users SET points=MAX(0,points-10) WHERE id=?", (session['user_id'],))
    db.commit(); db.close()
    flash('Registration cancelled.', 'info')
    return redirect(url_for('event_detail', eid=eid))

@app.route('/my_events')
@login_required
def my_events():
    db  = get_db()
    uid = session['user_id']
    evs  = db.execute("SELECT e.*, r.registered_at, r.attended FROM events e JOIN registrations r ON e.id=r.event_id WHERE r.user_id=? ORDER BY e.event_date ASC", (uid,)).fetchall()
    saved = db.execute("SELECT e.* FROM events e JOIN bookmarks b ON e.id=b.event_id WHERE b.user_id=? ORDER BY b.saved_at DESC", (uid,)).fetchall()
    user  = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    db.close()
    return render_template('my_events.html', events=evs, saved=saved, user=user)

@app.route('/feedback/<int:eid>', methods=['POST'])
@login_required
def submit_feedback(eid):
    rating  = int(request.form.get('rating', 3))
    comment = request.form.get('comment','').strip()
    db = get_db()
    try:
        db.execute("INSERT INTO feedback(user_id,event_id,rating,comment) VALUES(?,?,?,?)",
                   (session['user_id'],eid,rating,comment))
        db.execute("UPDATE users SET points=points+5 WHERE id=?", (session['user_id'],))
        ev = db.execute("SELECT title FROM events WHERE id=?", (eid,)).fetchone()
        push_notif(db, session['user_id'], f'Review submitted for "{ev["title"]}"! +5 points ⭐', f'/event/{eid}')
        db.commit()
        flash('Review submitted! +5 points earned ⭐', 'success')
    except sqlite3.IntegrityError: flash('You have already reviewed this event.', 'info')
    db.close()
    return redirect(url_for('event_detail', eid=eid))

@app.route('/bookmark/<int:eid>', methods=['POST'])
@login_required
def toggle_bookmark(eid):
    db  = get_db()
    uid = session['user_id']
    exists = db.execute("SELECT 1 FROM bookmarks WHERE user_id=? AND event_id=?", (uid,eid)).fetchone()
    if exists:
        db.execute("DELETE FROM bookmarks WHERE user_id=? AND event_id=?", (uid,eid))
        flash('Removed from saved events.', 'info')
    else:
        db.execute("INSERT INTO bookmarks(user_id,event_id) VALUES(?,?)", (uid,eid))
        flash('Event saved! ✓', 'success')
    db.commit(); db.close()
    return redirect(request.referrer or url_for('event_detail', eid=eid))

@app.route('/notifications')
@login_required
def notifications():
    db    = get_db()
    uid   = session['user_id']
    notifs = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 40", (uid,)).fetchall()
    db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (uid,))
    db.commit(); db.close()
    return render_template('notifications.html', notifs=notifs)

@app.route('/leaderboard')
def leaderboard():
    db = get_db()
    students = db.execute("""
        SELECT u.id, u.name, u.bio, u.points,
               COUNT(DISTINCT r.event_id) as event_count,
               COUNT(DISTINCT f.id) as review_count
        FROM users u
        LEFT JOIN registrations r ON u.id=r.user_id
        LEFT JOIN feedback f ON u.id=f.user_id
        WHERE u.role='student'
        GROUP BY u.id ORDER BY u.points DESC LIMIT 20
    """).fetchall()
    db.close()
    return render_template('leaderboard.html', students=students)

@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    db  = get_db()
    uid = session['user_id']
    if request.method == 'POST':
        name  = request.form['name'].strip()
        bio   = request.form.get('bio','').strip()
        phone = request.form.get('phone','').strip()
        p_errors = []
        if phone and not valid_phone(phone):
            p_errors.append('Invalid mobile number. Must be 10 digits starting with 6-9.')
        if p_errors:
            for e in p_errors: flash(e, 'error')
        else:
            clean_phone = normalise_phone(phone) if phone else ''
            # Check phone not taken by another user
            if clean_phone:
                taken = db.execute("SELECT id FROM users WHERE phone=? AND id!=? AND phone!=''",
                                   (clean_phone, uid)).fetchone()
                if taken:
                    flash('That mobile number is already used by another account.', 'error')
                    clean_phone = db.execute("SELECT phone FROM users WHERE id=?", (uid,)).fetchone()['phone']
            db.execute("UPDATE users SET name=?, bio=?, phone=? WHERE id=?", (name, bio, clean_phone or '', uid))
            session['name'] = name
            db.commit()
            flash('Profile updated!', 'success')
    user      = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    reg_count = db.execute("SELECT COUNT(*) FROM registrations WHERE user_id=?", (uid,)).fetchone()[0]
    rev_count = db.execute("SELECT COUNT(*) FROM feedback WHERE user_id=?", (uid,)).fetchone()[0]
    bm_count  = db.execute("SELECT COUNT(*) FROM bookmarks WHERE user_id=?", (uid,)).fetchone()[0]
    rank      = db.execute("SELECT COUNT()+1 FROM users WHERE role='student' AND points > (SELECT points FROM users WHERE id=?)", (uid,)).fetchone()[0]
    db.close()
    return render_template('profile.html', user=user, reg_count=reg_count,
                           rev_count=rev_count, bm_count=bm_count, rank=rank)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip()
        pw    = request.form['password']
        db    = get_db()
        user  = db.execute("SELECT * FROM users WHERE email=? AND password=?", (email, hash_pw(pw))).fetchone()
        db.close()
        if user:
            session.permanent  = True          # session survives browser restart
            session['user_id'] = user['id']
            session['name']    = user['name']
            session['role']    = user['role']
            flash(f'Welcome back, {user["name"]}! 👋', 'success')
            return redirect(url_for('admin_dashboard') if user['role']=='admin' else url_for('index'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        name  = request.form['name'].strip()
        email = request.form['email'].strip()
        phone = request.form.get('phone','').strip()
        pw    = request.form['password']
        pw2   = request.form['confirm']
        errors = []
        if not name:                 errors.append('Full name is required.')
        if not valid_email(email):   errors.append('Invalid email format.')
        if not phone:                errors.append('Mobile number is required.')
        elif not valid_phone(phone): errors.append('Enter a valid 10-digit Indian mobile number (starts with 6-9).')
        if len(pw) < 6:              errors.append('Password must be at least 6 characters.')
        if pw != pw2:                errors.append('Passwords do not match.')
        if not errors:
            clean_phone = normalise_phone(phone)
            db = get_db()
            # Check phone not already used
            dup_phone = db.execute("SELECT id FROM users WHERE phone=? AND phone!='' ", (clean_phone,)).fetchone()
            if dup_phone:
                errors.append('This mobile number is already registered.')
                db.close()
                for e in errors: flash(e, 'error')
                return render_template('register.html')
            try:
                db.execute("INSERT INTO users(name,email,password,role,phone,phone_verified) VALUES(?,?,?,?,?,?)",
                           (name, email, hash_pw(pw), 'student', clean_phone, 1))
                db.commit()
                new_id = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()['id']
                push_notif(db, new_id, 'Welcome to DreamCampus! Explore events and earn points.', '/events')
                db.commit()
                flash('Account created! Please login.', 'success')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                errors.append('Email already registered with another account.')
                db.close()
            else:
                db.close()
        for e in errors: flash(e, 'error')
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('index'))

@app.route('/inbox')
@login_required
def inbox():
    db   = get_db()
    uid  = session['user_id']
    msgs = db.execute("""
        SELECT m.*, u.name as sender_name, u.phone as sender_phone, e.title as event_title
        FROM messages m JOIN users u ON m.sender_id=u.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.receiver_id=? ORDER BY m.created_at DESC
    """, (uid,)).fetchall()
    unread = db.execute("SELECT COUNT(*) FROM messages WHERE receiver_id=? AND is_read=0", (uid,)).fetchone()[0]
    db.close()
    return render_template('inbox.html', messages=msgs, unread=unread)

@app.route('/message/read/<int:mid>')
@login_required
def mark_read(mid):
    db = get_db()
    db.execute("UPDATE messages SET is_read=1 WHERE id=?", (mid,))
    db.commit(); db.close()
    return redirect(url_for('inbox'))

@app.route('/message/send', methods=['GET','POST'])
@login_required
def send_message():
    db = get_db()
    if request.method == 'POST':
        receiver_id = request.form.get('receiver_id') or None
        event_id    = request.form.get('event_id') or None
        subject     = request.form['subject'].strip()
        body        = request.form['body'].strip()
        if not subject or not body:
            flash('Subject and body required.', 'error')
        else:
            db.execute("INSERT INTO messages(sender_id,receiver_id,event_id,subject,body) VALUES(?,?,?,?,?)",
                       (session['user_id'],receiver_id,event_id,subject,body))
            if receiver_id:
                push_notif(db, int(receiver_id), f'New message: "{subject}"', '/inbox')
            db.commit()
            flash('Message sent!', 'success')
            db.close()
            return redirect(url_for('inbox'))
    if session['role'] == 'admin':
        students = db.execute("SELECT id,name,email FROM users WHERE role='student' ORDER BY name").fetchall()
        events   = db.execute("SELECT id,title FROM events ORDER BY event_date").fetchall()
    else:
        students = None
        events   = db.execute("SELECT id,title FROM events ORDER BY event_date").fetchall()
    admin = db.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
    db.close()
    return render_template('send_message.html', students=students, events=events,
                           admin_id=admin['id'] if admin else None)

@app.route('/message/broadcast', methods=['POST'])
@login_required
@admin_required
def broadcast():
    db       = get_db()
    event_id = request.form.get('event_id') or None
    subject  = request.form['subject'].strip()
    body     = request.form['body'].strip()
    if event_id:
        students = db.execute("SELECT DISTINCT u.id FROM users u JOIN registrations r ON u.id=r.user_id WHERE r.event_id=?", (event_id,)).fetchall()
    else:
        students = db.execute("SELECT id FROM users WHERE role='student'").fetchall()
    for s in students:
        db.execute("INSERT INTO messages(sender_id,receiver_id,event_id,subject,body) VALUES(?,?,?,?,?)",
                   (session['user_id'],s['id'],event_id,subject,body))
        push_notif(db, s['id'], f'Announcement: "{subject}"', '/inbox')
    db.commit(); db.close()
    flash(f'Broadcast sent to {len(students)} student(s)!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/propose_event', methods=['GET','POST'])
@login_required
def propose_event():
    if session['role'] == 'admin': return redirect(url_for('add_event'))
    # Require verified phone before proposing
    db_chk = get_db()
    user_phone = db_chk.execute("SELECT phone FROM users WHERE id=?", (session['user_id'],)).fetchone()['phone']
    db_chk.close()
    if not user_phone:
        flash('⚠️ You must add your mobile number in your Profile before proposing an event.', 'error')
        return redirect(url_for('profile'))
    if request.method == 'POST':
        db = get_db()
        db.execute("""INSERT INTO event_proposals(student_id,title,description,proposed_date,proposed_time,venue,expected_participants,category)
                      VALUES(?,?,?,?,?,?,?,?)""",
                   (session['user_id'], request.form['title'].strip(), request.form['description'].strip(),
                    request.form['proposed_date'], request.form['proposed_time'],
                    request.form['venue'].strip(), int(request.form.get('expected_participants',50)),
                    request.form['category']))
        admin = db.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
        if admin:
            db.execute("INSERT INTO messages(sender_id,receiver_id,subject,body) VALUES(?,?,?,?)",
                       (session['user_id'],admin['id'],
                        f'New Proposal: {request.form["title"]}',
                        f'{session["name"]} submitted an event proposal. Review it in Admin → Proposals.'))
        db.commit(); db.close()
        flash('Proposal submitted! +15 points if approved 🚀', 'success')
        return redirect(url_for('my_proposals'))
    return render_template('propose_event.html')

@app.route('/my_proposals')
@login_required
def my_proposals():
    db    = get_db()
    props = db.execute("SELECT * FROM event_proposals WHERE student_id=? ORDER BY created_at DESC", (session['user_id'],)).fetchall()
    # Fetch student's phone so template can show guidance
    student_phone = db.execute("SELECT phone FROM users WHERE id=?", (session['user_id'],)).fetchone()['phone']
    db.close()
    return render_template('my_proposals.html', proposals=props, student_phone=student_phone)

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    db = get_db()
    stats = {
        'students':  db.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0],
        'events':    db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        'upcoming':  db.execute("SELECT COUNT(*) FROM events WHERE status='upcoming'").fetchone()[0],
        'regs':      db.execute("SELECT COUNT(*) FROM registrations").fetchone()[0],
        'proposals': db.execute("SELECT COUNT(*) FROM event_proposals WHERE status='pending'").fetchone()[0],
        'unread':    db.execute("SELECT COUNT(*) FROM messages WHERE receiver_id=? AND is_read=0", (session['user_id'],)).fetchone()[0],
    }
    recent_events = db.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT 5").fetchall()
    top_events    = db.execute("SELECT e.title, COUNT(r.user_id) as cnt FROM events e LEFT JOIN registrations r ON e.id=r.event_id GROUP BY e.id ORDER BY cnt DESC LIMIT 5").fetchall()
    pending_props = db.execute("SELECT p.*, u.name as student_name FROM event_proposals p JOIN users u ON p.student_id=u.id WHERE p.status='pending' ORDER BY p.created_at DESC LIMIT 3").fetchall()
    top_students  = db.execute("SELECT name, points FROM users WHERE role='student' ORDER BY points DESC LIMIT 5").fetchall()
    db.close()
    return render_template('admin/dashboard.html', stats=stats, recent_events=recent_events,
                           top_events=top_events, pending_props=pending_props, top_students=top_students)

@app.route('/admin/attendance/<int:eid>', methods=['GET','POST'])
@login_required
@admin_required
def attendance(eid):
    db = get_db()
    ev = db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    if request.method == 'POST':
        attended_ids = request.form.getlist('attended')
        db.execute("UPDATE registrations SET attended=0 WHERE event_id=?", (eid,))
        for uid in attended_ids:
            db.execute("UPDATE registrations SET attended=1 WHERE user_id=? AND event_id=?", (uid,eid))
            db.execute("UPDATE users SET points=points+20 WHERE id=?", (uid,))
            push_notif(db, int(uid), f'Attendance marked for "{ev["title"]}"! +20 points 🏆', f'/event/{eid}')
        db.commit()
        flash(f'Attendance saved! {len(attended_ids)} students got +20 points each.', 'success')
    students = db.execute("SELECT u.id, u.name, u.email, u.phone, r.attended, r.registered_at FROM registrations r JOIN users u ON r.user_id=u.id WHERE r.event_id=? ORDER BY u.name", (eid,)).fetchall()
    db.close()
    return render_template('admin/attendance.html', ev=dict(ev), students=students)

@app.route('/admin/proposals')
@login_required
@admin_required
def admin_proposals():
    db    = get_db()
    props = db.execute("""SELECT p.*, u.name as student_name, u.email as student_email, u.phone as student_phone
        FROM event_proposals p JOIN users u ON p.student_id=u.id
        ORDER BY CASE p.status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, p.created_at DESC""").fetchall()
    db.close()
    return render_template('admin/proposals.html', proposals=props)

@app.route('/admin/proposals/<int:pid>/<action>', methods=['POST'])
@login_required
@admin_required
def review_proposal(pid, action):
    db         = get_db()
    prop       = db.execute("SELECT * FROM event_proposals WHERE id=?", (pid,)).fetchone()
    admin_note = request.form.get('admin_note','')
    status     = 'approved' if action == 'approve' else 'rejected'
    db.execute("UPDATE event_proposals SET status=?, admin_note=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?", (status,admin_note,pid))
    if action == 'approve':
        # When approving proposal, admin can upload/paste an image too
        proposal_img = None
        if 'image_file' in request.files:
            proposal_img = save_uploaded_image(request.files['image_file'])
        if not proposal_img:
            proposal_img = request.form.get('image_url', '').strip()
        db.execute("""INSERT INTO events(title,description,event_date,event_time,venue,max_participants,category,status,image_url,created_by)
                      VALUES(?,?,?,?,?,?,?,?,?,?)""",
                   (prop['title'],prop['description'],prop['proposed_date'],prop['proposed_time'],
                    prop['venue'],prop['expected_participants'],prop['category'],'upcoming',
                    proposal_img, prop['student_id']))
        db.execute("UPDATE users SET points=points+15 WHERE id=?", (prop['student_id'],))
        push_notif(db, prop['student_id'], f'Proposal "{prop["title"]}" APPROVED! Now live + 15 pts 🎉', '/events')
        msg = f'Approved! "{prop["title"]}" is live.'
    else:
        push_notif(db, prop['student_id'], f'Proposal "{prop["title"]}" was not approved. Check inbox.', '/inbox')
        msg = 'Proposal rejected.'
    db.execute("INSERT INTO messages(sender_id,receiver_id,subject,body) VALUES(?,?,?,?)",
               (session['user_id'],prop['student_id'],
                f'Your Proposal: {status.upper()}',
                f'Your event proposal "{prop["title"]}" has been {status}.'
                +(' It is now live! +15 points earned.' if action=='approve' else f' Reason: {admin_note or "Contact admin."}')))
    db.commit(); db.close()
    flash(msg, 'success' if action=='approve' else 'info')
    return redirect(url_for('admin_proposals'))

@app.route('/admin/events')
@login_required
@admin_required
def admin_events():
    db  = get_db()
    evs = db.execute("SELECT * FROM events ORDER BY event_date DESC").fetchall()
    result = [{'ev':dict(ev),'count':db.execute("SELECT COUNT(*) FROM registrations WHERE event_id=?", (ev['id'],)).fetchone()[0]} for ev in evs]
    db.close()
    return render_template('admin/events.html', events=result)

@app.route('/admin/add_event', methods=['GET','POST'])
@login_required
@admin_required
def add_event():
    if request.method == 'POST':
        db = get_db()
        # Handle image: prefer uploaded file, fall back to URL field
        uploaded_url = None
        if 'image_file' in request.files:
            uploaded_url = save_uploaded_image(request.files['image_file'])
        final_image_url = uploaded_url or request.form.get('image_url', '').strip()

        db.execute("""INSERT INTO events(title,description,event_date,event_time,venue,max_participants,category,status,image_url,created_by)
                      VALUES(?,?,?,?,?,?,?,?,?,?)""",
                   (request.form['title'],request.form['description'],request.form['event_date'],
                    request.form['event_time'],request.form['venue'],int(request.form['max_participants']),
                    request.form['category'],request.form['status'],
                    final_image_url, session['user_id']))
        db.commit(); db.close()
        flash('Event added!', 'success')
        return redirect(url_for('admin_events'))
    return render_template('admin/add_event.html')

@app.route('/admin/edit_event/<int:eid>', methods=['GET','POST'])
@login_required
@admin_required
def edit_event(eid):
    db = get_db()
    ev = db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    if request.method == 'POST':
        # Handle image: prefer uploaded file, fall back to URL field, then keep existing
        uploaded_url = None
        if 'image_file' in request.files:
            uploaded_url = save_uploaded_image(request.files['image_file'])
        url_field   = request.form.get('image_url', '').strip()
        final_image = uploaded_url or url_field or (ev['image_url'] if ev else '')

        db.execute("""UPDATE events SET title=?,description=?,event_date=?,event_time=?,
                      venue=?,max_participants=?,category=?,status=?,image_url=? WHERE id=?""",
                   (request.form['title'],request.form['description'],request.form['event_date'],
                    request.form['event_time'],request.form['venue'],int(request.form['max_participants']),
                    request.form['category'],request.form['status'],
                    final_image, eid))
        db.commit(); db.close()
        flash('Event updated!', 'success')
        return redirect(url_for('admin_events'))
    db.close()
    return render_template('admin/add_event.html', ev=dict(ev), edit=True)

@app.route('/admin/delete_event/<int:eid>', methods=['POST'])
@login_required
@admin_required
def delete_event(eid):
    db = get_db()
    for tbl in ['registrations','feedback','bookmarks']:
        db.execute(f"DELETE FROM {tbl} WHERE event_id=?", (eid,))
    db.execute("DELETE FROM events WHERE id=?", (eid,))
    db.commit(); db.close()
    flash('Event deleted.', 'info')
    return redirect(url_for('admin_events'))

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    db    = get_db()
    users = db.execute("""SELECT u.*, COUNT(DISTINCT r.event_id) as reg_count
        FROM users u LEFT JOIN registrations r ON u.id=r.user_id
        GROUP BY u.id ORDER BY u.created_at DESC""").fetchall()
    db.close()
    return render_template('admin/users.html', users=users)

@app.route('/admin/change_role/<int:uid>', methods=['POST'])
@login_required
@admin_required
def change_role(uid):
    db = get_db()
    db.execute("UPDATE users SET role=? WHERE id=?", (request.form['role'],uid))
    db.commit(); db.close()
    flash('Role updated.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/analytics')
@login_required
@admin_required
def analytics():
    db = get_db()
    reg_data = db.execute("SELECT e.title, e.category, COUNT(r.user_id) as cnt FROM events e LEFT JOIN registrations r ON e.id=r.event_id GROUP BY e.id ORDER BY cnt DESC").fetchall()
    cat_data = db.execute("SELECT category, COUNT(*) as cnt FROM events GROUP BY category").fetchall()
    all_regs = db.execute("SELECT u.name, u.email, e.title, e.event_date, e.venue, r.registered_at FROM registrations r JOIN users u ON r.user_id=u.id JOIN events e ON r.event_id=e.id ORDER BY r.registered_at DESC").fetchall()
    db.close()
    return render_template('admin/analytics.html',
                           reg_data=[list(r) for r in reg_data],
                           cat_data=[list(r) for r in cat_data],
                           all_regs=all_regs)

@app.route('/admin/export_csv')
@login_required
@admin_required
def export_csv():
    db   = get_db()
    rows = db.execute("SELECT u.name, u.email, u.phone, e.title, e.event_date, e.venue, r.registered_at FROM registrations r JOIN users u ON r.user_id=u.id JOIN events e ON r.event_id=e.id ORDER BY r.registered_at DESC").fetchall()
    db.close()
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(['Student Name','Email','Mobile','Event','Event Date','Venue','Registered At'])
    for row in rows: w.writerow(list(row))
    out.seek(0)
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment;filename=registrations.csv'})

@app.context_processor
def inject_globals():
    data = {'unread_count': 0, 'notif_count': 0}
    if 'user_id' in session:
        db = get_db()
        data['unread_count'] = db.execute("SELECT COUNT(*) FROM messages WHERE receiver_id=? AND is_read=0", (session['user_id'],)).fetchone()[0]
        data['notif_count']  = db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (session['user_id'],)).fetchone()[0]
        db.close()
    return data

if __name__ == '__main__':
    setup_db()   # only creates tables — never deletes data
    app.run(host='0.0.0.0', port=5000, debug=True)
