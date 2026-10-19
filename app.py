from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, math, os, re, secrets, base64, tempfile
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get("ATTEND75_SECRET_KEY", "local-demo-secret-change-before-deployment")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "attendance.db")
SELFIE_DIR = os.path.join(BASE_DIR, "private_selfies")
FACE_DIR = os.path.join(BASE_DIR, "private_faces")
os.makedirs(SELFIE_DIR, exist_ok=True)
os.makedirs(FACE_DIR, exist_ok=True)

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        mobile TEXT UNIQUE NOT NULL,
        pin TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('student','teacher','admin')),
        college_id TEXT,
        consent_at TEXT
    );
    CREATE TABLE IF NOT EXISTS subjects(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        teacher_id INTEGER NOT NULL,
        lecture_minutes INTEGER NOT NULL DEFAULT 60,
        total_minutes INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(teacher_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS enrollments(
        student_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        PRIMARY KEY(student_id, subject_id)
    );
    CREATE TABLE IF NOT EXISTS sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER NOT NULL,
        teacher_id INTEGER NOT NULL,
        code TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ends_at TEXT NOT NULL,
        lat REAL,
        lon REAL,
        radius_m REAL DEFAULT 150,
        active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS attendance(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        joined_at TEXT NOT NULL,
        left_at TEXT,
        minutes INTEGER DEFAULT 0,
        UNIQUE(session_id, student_id)
    );
    """)
    # Safe, additive migration: preserve existing users, subjects and attendance.
    user_columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "college_id" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN college_id TEXT")
    if "consent_at" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN consent_at TEXT")
    if "face_file" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN face_file TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_college_id_unique ON users(college_id) WHERE college_id IS NOT NULL AND college_id != ''")
    attendance_columns = {row[1] for row in conn.execute("PRAGMA table_info(attendance)").fetchall()}
    if "selfie_file" not in attendance_columns:
        conn.execute("ALTER TABLE attendance ADD COLUMN selfie_file TEXT")
    if "face_status" not in attendance_columns:
        conn.execute("ALTER TABLE attendance ADD COLUMN face_status TEXT")
    # Demo data
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute("INSERT INTO users(name,mobile,pin,role) VALUES (?,?,?,?)",
                     ("Demo Teacher","9999999999","1234","teacher"))
        conn.execute("INSERT INTO users(name,mobile,pin,role) VALUES (?,?,?,?)",
                     ("Demo Student","8888888888","1234","student"))
        teacher = conn.execute("SELECT id FROM users WHERE mobile='9999999999'").fetchone()["id"]
        student = conn.execute("SELECT id FROM users WHERE mobile='8888888888'").fetchone()["id"]
        cur = conn.execute("""INSERT INTO subjects(name,teacher_id,lecture_minutes,total_minutes)
                              VALUES (?,?,?,?)""",
                           ("Professional Communication",teacher,60,0))
        sid = cur.lastrowid
        conn.execute("INSERT INTO enrollments(student_id,subject_id) VALUES (?,?)",(student,sid))
    conn.commit()
    conn.close()

def current_user():
    if "user_id" not in session:
        return None
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()
    return user

def login_required(role=None):
    user = current_user()
    if not user or (role and user["role"] != role):
        return False
    return True

@app.route("/")
def index():
    if current_user():
        return redirect(url_for("dashboard"))
    return render_template("index.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        mobile = request.form["mobile"].strip()
        pin = request.form["pin"].strip()
        conn = db()
        user = conn.execute("SELECT * FROM users WHERE mobile=?", (mobile,)).fetchone()
        conn.close()
        valid_pin = False
        if user:
            stored_pin = user["pin"]
            # New accounts store a password hash; legacy demo accounts remain compatible.
            if stored_pin.startswith("scrypt:") or stored_pin.startswith("pbkdf2:"):
                try:
                    valid_pin = check_password_hash(stored_pin, pin)
                except ValueError:
                    valid_pin = False
            else:
                valid_pin = secrets.compare_digest(stored_pin, pin)
        if user and valid_pin:
            session["user_id"] = user["id"]
            session["user_role"] = user["role"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))
        flash("Invalid registered mobile number or PIN.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/dashboard")
def dashboard():
    user = current_user()
    if not user: return redirect(url_for("login"))
    conn = db()
    if user["role"] == "student":
        rows = conn.execute("""
            SELECT s.id, s.name, s.lecture_minutes,
                   COALESCE(SUM(a.minutes),0) AS attended_minutes,
                   COALESCE(SUM(CASE WHEN a.minutes > 0 THEN 1 ELSE 0 END),0) AS attended_lectures,
                   COUNT(DISTINCT se.id) AS conducted_lectures
            FROM enrollments e
            JOIN subjects s ON s.id=e.subject_id
            LEFT JOIN sessions se ON se.subject_id=s.id
            LEFT JOIN attendance a ON a.session_id=se.id AND a.student_id=e.student_id
            WHERE e.student_id=?
            GROUP BY s.id
        """,(user["id"],)).fetchall()
        data=[]
        for r in rows:
            total_minutes = int(r["conducted_lectures"])*int(r["lecture_minutes"])
            pct = (r["attended_minutes"]/total_minutes*100) if total_minutes else 0
            required = math.ceil(r["conducted_lectures"]*0.75)
            data.append({**dict(r),"total_minutes":total_minutes,"percentage":round(pct,1),
                         "required_lectures":required,
                         "status":"Eligible" if pct>=75 else "Below 75%"})
        conn.close()
        return render_template("student_dashboard.html", user=user, subjects=data)
    elif user["role"] == "teacher":
        subjects = conn.execute("SELECT * FROM subjects WHERE teacher_id=?",(user["id"],)).fetchall()
        sessions = conn.execute("""
            SELECT se.*, s.name subject_name,
                   (SELECT COUNT(*) FROM attendance a WHERE a.session_id=se.id) present
            FROM sessions se JOIN subjects s ON s.id=se.subject_id
            WHERE se.teacher_id=? ORDER BY se.id DESC LIMIT 20
        """,(user["id"],)).fetchall()
        conn.close()
        return render_template("teacher_dashboard.html",user=user,subjects=subjects,sessions=sessions)
    students = conn.execute("SELECT id, name, college_id, mobile, role, face_file FROM users WHERE role='student' ORDER BY name").fetchall()
    teachers = conn.execute("""
        SELECT u.id, u.name, u.college_id, u.mobile,
               GROUP_CONCAT(s.name, ', ') AS subject_names
        FROM users u
        LEFT JOIN subjects s ON s.teacher_id=u.id
        WHERE u.role='teacher'
        GROUP BY u.id
        ORDER BY u.name
    """).fetchall()
    available_subjects = conn.execute("SELECT id, name FROM subjects ORDER BY name").fetchall()
    student_count = len(students)
    conn.close()
    return render_template("admin_dashboard.html", user=user, students=students,
                           teachers=teachers, teacher_count=len(teachers),
                           student_count=student_count, available_subjects=available_subjects)

@app.route("/setup-admin", methods=["GET", "POST"])
def setup_admin():
    """One-time local bootstrap. Automatically disables after the first admin exists."""
    conn = db()
    exists = conn.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone()
    if exists:
        conn.close()
        flash("Admin setup is already complete. Please sign in.")
        return redirect(url_for("login"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        mobile = request.form.get("mobile", "").strip()
        pin = request.form.get("pin", "").strip()
        pin_confirm = request.form.get("pin_confirm", "").strip()
        consent = request.form.get("consent") == "yes"
        if not consent:
            flash("Please confirm that you are setting up this local project on your own device.")
        elif not name or not re.fullmatch(r"[0-9]{10}", mobile):
            flash("Enter your name and a valid 10-digit mobile number.")
        elif not re.fullmatch(r"[0-9]{4,8}", pin) or pin != pin_confirm:
            flash("PINs must match and contain 4–8 digits.")
        else:
            try:
                conn.execute("INSERT INTO users(name,mobile,pin,role) VALUES (?,?,?,'admin')",
                             (name, mobile, generate_password_hash(pin)))
                conn.commit()
                conn.close()
                flash("Admin account created. Sign in with your mobile number and PIN.")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That mobile number is already registered. Use a different number.")
    conn.close()
    return render_template("setup_admin.html")

@app.route("/admin/students", methods=["POST"])
def add_student():
    user = current_user()
    if not user or user["role"] != "admin":
        flash("Only an admin can register students.")
        return redirect(url_for("login"))
    name = request.form.get("name", "").strip()
    college_id = request.form.get("college_id", "").strip().upper()
    mobile = request.form.get("mobile", "").strip()
    pin = request.form.get("pin", "").strip()
    consent = request.form.get("consent") == "yes"
    selected_subject_ids = request.form.getlist("subject_ids")
    if not consent:
        flash("Registration not saved: confirm that the student has agreed to use these details for this demo.")
    elif not name or not re.fullmatch(r"[A-Z0-9/-]{3,30}", college_id):
        flash("Enter a name and a valid college ID (3–30 letters, digits, / or -).")
    elif not re.fullmatch(r"[0-9]{10}", mobile):
        flash("Mobile number must contain exactly 10 digits.")
    elif not re.fullmatch(r"[0-9]{4,8}", pin):
        flash("PIN must contain 4–8 digits.")
    else:
        conn = db()
        try:
            cur = conn.execute("INSERT INTO users(name,mobile,pin,role,college_id,consent_at) VALUES (?,?,?,'student',?,?)",
                               (name, mobile, generate_password_hash(pin), college_id, datetime.now().isoformat(timespec="seconds")))
            new_student_id = cur.lastrowid
            valid_subjects = {str(row["id"]) for row in conn.execute("SELECT id FROM subjects").fetchall()}
            for subject_id in selected_subject_ids:
                if subject_id in valid_subjects:
                    conn.execute("INSERT OR IGNORE INTO enrollments(student_id,subject_id) VALUES (?,?)", (new_student_id, int(subject_id)))
            conn.commit()
            flash(f"Student {college_id} registered successfully.")
        except sqlite3.IntegrityError:
            conn.rollback()
            flash("Registration failed: the mobile number or college ID is already registered.")
        finally:
            conn.close()
    return redirect(url_for("dashboard"))

@app.route("/admin/teachers", methods=["POST"])
def add_teacher():
    user = current_user()
    if not user or user["role"] != "admin":
        flash("Only an admin can register teachers.")
        return redirect(url_for("login"))

    name = request.form.get("name", "").strip()
    college_id = request.form.get("college_id", "").strip().upper()
    mobile = request.form.get("mobile", "").strip()
    pin = request.form.get("pin", "").strip()
    subject_name = request.form.get("subject_name", "").strip()
    try:
        lecture_minutes = int(request.form.get("lecture_minutes", "60"))
    except ValueError:
        lecture_minutes = 0
    consent = request.form.get("consent") == "yes"

    if not consent:
        flash("Teacher registration not saved: confirm the faculty member has agreed to this demo.")
    elif not name or not re.fullmatch(r"[A-Z0-9/-]{3,30}", college_id):
        flash("Enter a name and a valid faculty ID (3–30 letters, digits, / or -).")
    elif not re.fullmatch(r"[0-9]{10}", mobile):
        flash("Mobile number must contain exactly 10 digits.")
    elif not re.fullmatch(r"[0-9]{4,8}", pin):
        flash("PIN must contain 4–8 digits.")
    elif not subject_name or len(subject_name) > 100:
        flash("Enter a subject name (up to 100 characters).")
    elif not 1 <= lecture_minutes <= 600:
        flash("Lecture duration must be between 1 and 600 minutes.")
    else:
        conn = db()
        try:
            cur = conn.execute(
                "INSERT INTO users(name,mobile,pin,role,college_id,consent_at) VALUES (?,?,?,'teacher',?,?)",
                (name, mobile, generate_password_hash(pin), college_id,
                 datetime.now().isoformat(timespec="seconds"))
            )
            teacher_id = cur.lastrowid
            conn.execute(
                "INSERT INTO subjects(name,teacher_id,lecture_minutes,total_minutes) VALUES (?,?,?,0)",
                (subject_name, teacher_id, lecture_minutes)
            )
            conn.commit()
            flash(f"Teacher {college_id} registered and assigned subject '{subject_name}'.")
        except sqlite3.IntegrityError:
            conn.rollback()
            flash("Registration failed: that mobile number or faculty ID is already registered.")
        finally:
            conn.close()
    return redirect(url_for("dashboard"))


@app.route("/admin/students/<int:student_id>/delete", methods=["POST"])
def delete_student(student_id):
    user = current_user()
    if not user or user["role"] != "admin":
        return jsonify(ok=False, error="admin required"), 403
    conn = db()
    student = conn.execute("SELECT id, role FROM users WHERE id=?", (student_id,)).fetchone()
    if not student or student["role"] != "student":
        conn.close()
        flash("Student record not found.")
        return redirect(url_for("dashboard"))
    # Keep referential history; disable deletion when attendance/enrolment records exist.
    linked = conn.execute("SELECT 1 FROM attendance WHERE student_id=? UNION SELECT 1 FROM enrollments WHERE student_id=? LIMIT 1", (student_id, student_id)).fetchone()
    if linked:
        conn.close()
        flash("This student has attendance or enrollment history, so the record was kept to preserve records.")
    else:
        conn.execute("DELETE FROM users WHERE id=? AND role='student'", (student_id,))
        conn.commit(); conn.close()
        flash("Student record removed.")
    return redirect(url_for("dashboard"))

@app.route("/teacher/create-session", methods=["POST"])
def create_session():
    user=current_user()
    if not user or user["role"]!="teacher": return redirect(url_for("login"))
    subject_id=int(request.form["subject_id"])
    code=request.form["code"].strip().upper() or "CLASS75"
    lat=request.form.get("lat") or None
    lon=request.form.get("lon") or None
    radius=float(request.form.get("radius") or 150)
    duration=int(request.form.get("duration") or 60)
    start=datetime.now()
    end=start+timedelta(minutes=duration)
    conn=db()
    # Record a new lecture as a conducted session.
    conn.execute("""INSERT INTO sessions(subject_id,teacher_id,code,started_at,ends_at,lat,lon,radius_m,active)
                    VALUES (?,?,?,?,?,?,?,?,1)""",
                 (subject_id,user["id"],code,start.isoformat(timespec="seconds"),end.isoformat(timespec="seconds"),lat,lon,radius))
    conn.commit(); conn.close()
    flash(f"Attendance session created. Code: {code}")
    return redirect(url_for("dashboard"))

@app.route("/teacher/session/<int:session_id>/attendance")
def teacher_session_attendance(session_id):
    """Show attendance roster and captured selfies only to the session's teacher."""
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if user["role"] != "teacher":
        abort(403)

    conn = db()
    lecture = conn.execute("""
        SELECT se.id, se.code, se.started_at, se.ends_at, se.active,
               sub.name AS subject_name
        FROM sessions se
        JOIN subjects sub ON sub.id = se.subject_id
        WHERE se.id = ? AND se.teacher_id = ?
    """, (session_id, user["id"])).fetchone()
    if not lecture:
        conn.close()
        abort(404)

    attendees = conn.execute("""
        SELECT a.id AS attendance_id, a.joined_at, a.left_at, a.minutes,
               a.selfie_file, u.name AS student_name,
               COALESCE(NULLIF(u.college_id, ''), 'Not added') AS roll_number
        FROM attendance a
        JOIN users u ON u.id = a.student_id
        WHERE a.session_id = ?
        ORDER BY a.joined_at ASC, u.name COLLATE NOCASE ASC
    """, (session_id,)).fetchall()
    conn.close()
    return render_template("teacher_attendance.html", user=user,
                           lecture=lecture, attendees=attendees)




def deepface_verify(reference_path, live_path):
    """Return (matched, message); DeepFace is an optional dependency."""
    try:
        from deepface import DeepFace
    except ImportError:
        return None, "Face verification is not installed. Follow README_FACE_RECOGNITION.md."
    try:
        result = DeepFace.verify(
            img1_path=reference_path, img2_path=live_path,
            model_name="Facenet512", detector_backend="opencv",
            enforce_detection=True, align=True
        )
        return bool(result.get("verified")), "Face matched." if result.get("verified") else "Face did not match."
    except Exception:
        return None, "Could not verify the face. Use one clear, well-lit face and try again."

@app.route("/admin/face-enroll/<int:student_id>", methods=["GET", "POST"])
def admin_face_enroll(student_id):
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if user["role"] != "admin":
        abort(403)
    conn = db()
    student = conn.execute("SELECT id,name,college_id,face_file FROM users WHERE id=? AND role='student'", (student_id,)).fetchone()
    if not student:
        conn.close()
        abort(404)
    if request.method == "POST":
        if request.form.get("face_consent") != "yes":
            conn.close()
            flash("Confirm the student's consent to face verification.")
            return redirect(url_for("admin_face_enroll", student_id=student_id))
        data = request.form.get("face_data", "")
        try:
            if not data.startswith("data:image/jpeg;base64,"):
                raise ValueError()
            raw = base64.b64decode(data.split(",", 1)[1], validate=True)
            if len(raw) > 2_000_000 or not raw.startswith(bytes.fromhex("ffd8ff")):
                raise ValueError()
        except (ValueError, base64.binascii.Error):
            conn.close()
            flash("Capture a valid JPEG face photo and try again.")
            return redirect(url_for("admin_face_enroll", student_id=student_id))
        try:
            from deepface import DeepFace
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp.write(raw)
                temp_path = tmp.name
            try:
                DeepFace.extract_faces(img_path=temp_path, detector_backend="opencv", enforce_detection=True, align=True)
            finally:
                try: os.remove(temp_path)
                except OSError: pass
        except ImportError:
            conn.close()
            flash("Face engine is not installed. Follow README_FACE_RECOGNITION.md.")
            return redirect(url_for("admin_face_enroll", student_id=student_id))
        except Exception:
            conn.close()
            flash("No clear face detected. Capture one face in good lighting.")
            return redirect(url_for("admin_face_enroll", student_id=student_id))
        face_name = f"student_{student_id}_{secrets.token_hex(10)}.jpg"
        with open(os.path.join(FACE_DIR, face_name), "wb") as f:
            f.write(raw)
        old_face = student["face_file"]
        conn.execute("UPDATE users SET face_file=? WHERE id=?", (face_name, student_id))
        conn.commit()
        conn.close()
        if old_face:
            try: os.remove(os.path.join(FACE_DIR, os.path.basename(old_face)))
            except OSError: pass
        flash("Reference face enrolled successfully.")
        return redirect(url_for("dashboard"))
    conn.close()
    return render_template("face_enroll.html", user=user, student=student)

@app.route("/teacher/attendance-selfie/<int:attendance_id>")
def teacher_attendance_selfie(attendance_id):
    """Serve a private selfie only to the teacher who owns its lecture."""
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if user["role"] != "teacher":
        abort(403)

    conn = db()
    row = conn.execute("""
        SELECT a.selfie_file
        FROM attendance a
        JOIN sessions se ON se.id = a.session_id
        WHERE a.id = ? AND se.teacher_id = ?
    """, (attendance_id, user["id"])).fetchone()
    conn.close()
    if not row or not row["selfie_file"]:
        abort(404)
    # Filenames are generated by the server and images live outside /static.
    filename = os.path.basename(row["selfie_file"])
    response = send_from_directory(SELFIE_DIR, filename, mimetype="image/jpeg", as_attachment=False)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.route("/teacher/close/<int:session_id>", methods=["POST"])
def close_session(session_id):
    user=current_user()
    if not user or user["role"]!="teacher": return jsonify(ok=False),403
    conn=db()
    conn.execute("UPDATE sessions SET active=0 WHERE id=? AND teacher_id=?",(session_id,user["id"]))
    # Close open attendance records and calculate actual minutes.
    rows=conn.execute("""SELECT id,joined_at FROM attendance
                         WHERE session_id=? AND left_at IS NULL""",(session_id,)).fetchall()
    now=datetime.now()
    for r in rows:
        joined=datetime.fromisoformat(r["joined_at"])
        mins=max(0,int((now-joined).total_seconds()/60))
        conn.execute("UPDATE attendance SET left_at=?,minutes=? WHERE id=?",
                     (now.isoformat(timespec="seconds"),mins,r["id"]))
    conn.commit(); conn.close()
    return jsonify(ok=True)

@app.route("/student/join", methods=["GET","POST"])
def join():
    user=current_user()
    if not user or user["role"]!="student": return redirect(url_for("login"))
    conn=db()
    subjects=conn.execute("""
        SELECT s.* FROM subjects s JOIN enrollments e ON e.subject_id=s.id
        WHERE e.student_id=?
    """,(user["id"],)).fetchall()
    if request.method=="POST":
        code=request.form.get("code", "").strip().upper()
        lat=request.form.get("lat")
        lon=request.form.get("lon")
        selfie_data=request.form.get("selfie_data", "")
        consent=request.form.get("selfie_consent") == "on"
        if not consent:
            conn.close(); flash("Please confirm consent to capture a selfie for attendance verification."); return redirect(url_for("join"))
        if not selfie_data.startswith("data:image/jpeg;base64,"):
            conn.close(); flash("Take a fresh selfie with your camera before submitting attendance."); return redirect(url_for("join"))
        try:
            encoded=selfie_data.split(",",1)[1]
            if len(encoded) > 4_000_000:
                raise ValueError("image too large")
            image_bytes=base64.b64decode(encoded, validate=True)
            if not image_bytes.startswith(bytes.fromhex("ffd8ff")) or len(image_bytes) > 3_000_000:
                raise ValueError("invalid image")
        except (ValueError, base64.binascii.Error):
            conn.close(); flash("Selfie image was invalid or too large. Please capture it again."); return redirect(url_for("join"))
        now=datetime.now()
        s=conn.execute("""SELECT se.*, sub.name subject_name
                          FROM sessions se JOIN subjects sub ON sub.id=se.subject_id
                          WHERE se.code=? AND se.active=1 AND se.ends_at>?""",
                       (code,now.isoformat())).fetchone()
        if not s:
            conn.close(); flash("Invalid/expired attendance code."); return redirect(url_for("join"))
        # Browser geolocation is optional for local/demo use.
        if s["lat"] is not None and s["lon"] is not None and lat and lon:
            distance=haversine(float(lat),float(lon),float(s["lat"]),float(s["lon"]))
            if distance > s["radius_m"]:
                conn.close(); flash(f"Outside classroom area ({int(distance)} m away)."); return redirect(url_for("join"))
        existing=conn.execute("SELECT id FROM attendance WHERE session_id=? AND student_id=?",
                              (s["id"],user["id"])).fetchone()
        if existing:
            conn.close(); flash("Attendance already marked for this lecture."); return redirect(url_for("dashboard"))
        # Require an enrolled reference face and compare it before accepting attendance.
        if not user["face_file"]:
            conn.close()
            flash("Face verification is not enrolled for your account. Please contact the college admin.")
            return redirect(url_for("join"))
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as live_tmp:
            live_tmp.write(image_bytes)
            live_path = live_tmp.name
        try:
            matched, face_message = deepface_verify(
                os.path.join(FACE_DIR, os.path.basename(user["face_file"])), live_path
            )
        finally:
            try: os.remove(live_path)
            except OSError: pass
        if matched is None:
            conn.close()
            flash(face_message)
            return redirect(url_for("join"))
        if not matched:
            conn.close()
            flash("Face did not match your enrolled reference. Attendance was not marked. Ask your teacher for review if this is a mistake.")
            return redirect(url_for("join"))
        # Store selfie outside /static so student identity images are not publicly addressable.
        selfie_name=f"attendance_{s['id']}_{user['id']}_{secrets.token_hex(8)}.jpg"
        selfie_path=os.path.join(SELFIE_DIR, selfie_name)
        with open(selfie_path, "wb") as selfie_file:
            selfie_file.write(image_bytes)
        try:
            conn.execute("""INSERT INTO attendance(session_id,student_id,joined_at,selfie_file,face_status)
                            VALUES (?,?,?,?,?)""",(s["id"],user["id"],now.isoformat(timespec="seconds"),selfie_name,"verified"))
            conn.commit()
        except Exception:
            try: os.remove(selfie_path)
            except OSError: pass
            conn.close(); raise
        conn.close()
        flash(f"Attendance marked for {s['subject_name']}.")
        return redirect(url_for("dashboard"))
    conn.close()
    return render_template("join.html",user=user,subjects=subjects)

def haversine(lat1,lon1,lat2,lon2):
    from math import radians,sin,cos,asin,sqrt
    R=6371000
    dlat=radians(lat2-lat1); dlon=radians(lon2-lon1)
    a=sin(dlat/2)**2+cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2*R*asin(sqrt(a))

@app.route("/api/attendance/<int:subject_id>")
def attendance_api(subject_id):
    user=current_user()
    if not user: return jsonify(error="login required"),401
    conn=db()
    rows=conn.execute("""
        SELECT u.name,u.mobile,se.started_at,se.ends_at,a.joined_at,a.left_at,a.minutes
        FROM attendance a
        JOIN users u ON u.id=a.student_id
        JOIN sessions se ON se.id=a.session_id
        WHERE se.subject_id=?
        ORDER BY se.started_at DESC
    """,(subject_id,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
