# Attend75 Face Verification Upgrade (ITM GIDA demo)

This is an upgrade based on the uploaded Attend75 Teacher Selfie Roster project.

## Important compatibility note
The original project can run without the face engine, but attendance submission now requires an enrolled reference face and DeepFace verification. The face-recognition stack (TensorFlow/DeepFace) may not support Python 3.14 yet. Use **Python 3.11 or 3.12** in a separate virtual environment for this feature. Do not uninstall or replace your current Python installation.

## Install (Windows / VS Code)
1. Back up your existing project folder, `attendance.db`, `private_selfies`, and any other private data.
2. Open this `attend75_work` folder in VS Code.
3. Open Terminal > New Terminal.
4. Check `python --version`. If it says 3.14, install Python 3.11 or 3.12 from python.org, then create a new environment with that interpreter. In VS Code use `Ctrl+Shift+P` > `Python: Select Interpreter`.
5. Create and activate a virtual environment:
   - `py -3.11 -m venv .venv`
   - `.\.venv\Scripts\Activate.ps1`
6. Install the regular dependencies:
   - `python -m pip install -r requirements.txt`
7. Install face verification separately (large download; first verification downloads model weights):
   - `python -m pip install -r requirements-face.txt`
8. Run `python app.py`.

If PowerShell blocks activation, use the selected interpreter directly: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` and then `.\.venv\Scripts\python.exe -m pip install -r requirements-face.txt`; run with `.\.venv\Scripts\python.exe app.py`.

## Enroll reference faces
1. Sign in as an admin.
2. Open Admin Dashboard > Student records.
3. Click **Enroll face** beside a student.
4. Obtain informed consent, start camera, capture one clear face, check the consent box and save.
5. Enroll each student separately. Reference files are stored in `private_faces`, outside `static`.

## Student attendance
Students must be logged in, enrolled with a reference face, take a fresh selfie, and submit an active teacher attendance code. DeepFace compares the new image with the enrolled reference before marking attendance. Attendance table receives additive `face_status` column. Existing database records are not intentionally removed.

## Limitations and safety
- Face matching is probabilistic; false matches and false rejections are possible.
- This package does **not** implement robust liveness detection. A matching face image on another screen could still fool a basic face comparison. Add a tested liveness solution and rotating QR/session checks before real use.
- Keep a teacher review/manual alternative for mismatches. Never rely on face matching alone for disciplinary decisions.
- Get college approval and informed consent, limit access, secure backups, define deletion/retention, and do not deploy with the demo secret key.
- Face data is sensitive. This is a student project prototype, not a certified biometric attendance product.
