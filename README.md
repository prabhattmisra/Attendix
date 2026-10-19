# Attend75 — ITM GIDA Dark Premium UI

A Flask + SQLite attendance-management project with a dark premium interface, responsive layouts, student attendance analytics, and ITM GIDA / Gorakhpur project branding.

> **Important:** Attend75 is a student project prototype, not an official ITM GIDA service. Use real student/faculty information only with their consent and appropriate approval.

## What's updated

- Dark navy dashboard with mint/blue accent colors, cards, sidebar navigation, and campus identity.
- Responsive sidebar/menu for mobile screens.
- Student overview metrics, subject attendance bars, a 75% target marker, progress ring, and subject cards.
- Existing student, teacher, admin, registration, session creation, session closing, and attendance routes/templates retained.
- Existing SQLite schema and records are not intentionally changed by this UI update. No database is included in this source archive.
- Login stores the display name in the Flask session for the top navigation. Existing PIN verification remains compatible with legacy demo PINs and hashed PINs.

## Files to replace

Copy these files into your existing project, replacing the same paths:

- `app.py`
- `static/style.css`
- `templates/base.html`
- `templates/student_dashboard.html`

All other templates and files are retained from the latest Attend75 ITM GIDA teacher-registration project.

## Safe update steps (Windows)

1. Stop Flask in the terminal with `Ctrl+C`.
2. Make a copy of your entire project folder, especially `attendance.db`.
3. Extract this ZIP into a temporary folder.
4. Copy the four files listed above into the matching locations in your current project and choose **Replace** when prompted.
5. Do **not** delete or replace your existing `attendance.db`.
6. Open Command Prompt in the project folder and activate your existing virtual environment if you use one.
7. Install dependencies if needed:

   ```bash
   pip install -r requirements.txt
   ```

8. Start the app:

   ```bash
   python app.py
   ```

9. Open `http://127.0.0.1:5000`.

## Configuration notes

- For local development, set a strong `ATTEND75_SECRET_KEY` environment variable before deployment. The default value is intended only for a local demo.
- Google Fonts are loaded from Google Fonts when internet access is available; system fallbacks are defined.
- Charts are drawn with HTML/CSS; no charting CDN or external JavaScript package is required.
- Do not deploy this demo with real student data until authentication, CSRF protection, HTTPS, permissions, backups, and privacy handling have been reviewed.

## Demo login (only if your database has the original demo accounts)

- Student: mobile `8888888888`, PIN `1234`
- Teacher: mobile `9999999999`, PIN `1234`

If these accounts were removed or changed in your existing database, use your existing credentials instead.

## Selfie attendance mode (new)
- Students must capture a fresh JPEG selfie through the browser camera and tick a consent checkbox before attendance can be submitted.
- The database migration adds `attendance.selfie_file` if it does not already exist; it does not delete or rewrite existing attendance records.
- Images are stored in `private_selfies/`, outside Flask's public `static/` directory. Restrict OS folder access and define a retention/deletion policy before real deployment.
- Camera access requires `localhost` during development or HTTPS when hosted.
- A selfie capture is not true liveness detection and cannot guarantee that proxy attendance is impossible. For stronger verification, use rotating QR sessions, classroom geofencing, and a carefully tested liveness/face-verification provider with explicit consent and a manual fallback.
- Back up `attendance.db` and the project before updating. Test camera permission, denied location, expired codes, duplicate submissions, and all student/teacher/admin workflows.
