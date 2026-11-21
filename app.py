import os
import io
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
from datetime import date
from functools import wraps
from PIL import Image
from flask import Flask, redirect, render_template_string, request, session, url_for
from supabase import Client, create_client
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = "clinicdesk_secure_random_secret_key"

# ClinicDesk Supabase Credentials
SUPABASE_URL = "https://pfmldhpidblncypuagld.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBmbWxkaHBpZGJsbmN5cHVhZ2xkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTQ2NTM2MjEsImV4cCI6MjExMDIyOTYyMX0.SI7i2c5IeGwP3T3qi0GaCEPU-WUeRFP2T4oh0Ioun0c"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

KEY_FILE = ".gemini_key.txt"


def get_active_gemini_key():
    """Reads the Gemini API key from Render environment variables or local fallback."""
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "r") as f:
            saved_key = f.read().strip()
            if saved_key:
                return saved_key
    return ""


def get_clinic_info(user_id):
    """Fetches clinic, doctor display details, and 4-digit PIN for a given user_id."""
    if not user_id:
        return {"clinic_name": "ClinicDesk", "doctor_name": "Doctor", "doctor_pin": "1234"}
    try:
        res = supabase.table('clinics').select('*').eq('user_id', user_id).execute()
        if res.data:
            return {
                "clinic_name": res.data[0].get("clinic_name") or "ClinicDesk",
                "doctor_name": res.data[0].get("doctor_name") or "Doctor",
                "doctor_pin": str(res.data[0].get("doctor_pin") or "1234")
            }
    except Exception:
        pass
    return {"clinic_name": "ClinicDesk", "doctor_name": "Doctor", "doctor_pin": "1234"}


def generate_share_token(patient_id, phone):
    """Generates a deterministic, unguessable read-only share token per patient."""
    raw = f"{patient_id}:{phone}".encode("utf-8")
    return hmac.new(app.secret_key.encode("utf-8"), raw, hashlib.sha256).hexdigest()[:16]


def format_whatsapp_phone(phone):
    """Formats Indian 10-digit numbers with 91 country code for wa.me links."""
    digits = "".join(filter(str.isdigit, str(phone or "")))
    if len(digits) == 10:
        return f"91{digits}"
    return digits


def compress_image_for_ocr(file_bytes, mime_type):
    """Resizes large phone photos to max 1600px JPEG to prevent Render OOM and speed up OCR."""
    if not mime_type or not mime_type.startswith("image/"):
        return file_bytes, mime_type
    try:
        img = Image.open(io.BytesIO(file_bytes))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return file_bytes, mime_type


def extract_medical_file_with_ai(file_bytes, mime_type, document_type="Prescription"):
    """Scan-aware medical OCR with radiology observation disclaimer for imaging scans."""
    api_key = get_active_gemini_key()
    if not api_key:
        return "AI API Key not configured.", "OCR skipped. Please verify GEMINI_API_KEY in server environment."

    file_bytes, mime_type = compress_image_for_ocr(file_bytes, mime_type)

    imaging_types = {"X-Ray", "Ultrasound", "MRI"}
    is_imaging_scan = document_type in imaging_types

    if is_imaging_scan:
        prompt_text = (
            f"You are assisting a physician reviewing a {document_type} image or report. "
            "Extract visible anatomical observations, printed film labels, measurements, or report text strictly in two sections:\n"
            "DIAGNOSIS: [Scan region / suspected finding or impression]\n"
            "NOTES: [Detailed visual observations, measurements, and printed text clearly]"
        )
    else:
        prompt_text = (
            f"Extract the medical details from this {document_type} strictly in two sections:\n"
            "DIAGNOSIS: [Suspected condition, symptoms, or test names]\n"
            "NOTES: [All medications, dosages, lab values, and doctor instructions clearly]"
        )

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key
    }
    encoded_data = base64.b64encode(file_bytes).decode('utf-8')

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt_text},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": encoded_data
                        }
                    }
                ]
            }
        ]
    }

    models_to_try = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    errors = []

    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=90)
            result = response.json()

            if "candidates" in result:
                text = result["candidates"][0]["content"]["parts"][0]["text"]
                diagnosis = "AI Extracted Report"
                notes = text

                if "DIAGNOSIS:" in text and "NOTES:" in text:
                    parts = text.split("NOTES:")
                    diag_part = parts[0].replace("DIAGNOSIS:", "").strip()
                    if diag_part:
                        diagnosis = diag_part[:100]
                    notes = parts[1].strip()

                if is_imaging_scan:
                    notes = f"⚠️ [AI Preliminary Image Observation — Verify with Radiologist Report]\n{notes}"

                return diagnosis, notes

            err_msg = result.get("error", {}).get("message", str(result))
            errors.append(f"{model_name}: {err_msg}")
        except Exception as e:
            errors.append(f"{model_name}: {str(e)}")
            time.sleep(1)

    return "General Consultation", f"Gemini API Error: {' | '.join(errors)}"


def render_attachments_gallery(prescriptions_list, max_height="140px", show_large_link=False):
    """Renders all attached scans/reports for a single visit in a clean horizontal grid."""
    if not prescriptions_list:
        return ""
    cards = ""
    for idx, rx in enumerate(prescriptions_list, 1):
        rx_url = rx.get('prescription_url', '')
        doc_type = rx.get('document_type', 'Report')
        if rx_url.lower().endswith('.pdf'):
            preview = f'<a href="{rx_url}" target="_blank" class="btn btn-sm btn-outline-secondary d-block">📄 Open PDF #{idx}</a>'
        else:
            preview = f'''
            <a href="{rx_url}" target="_blank">
                <img src="{rx_url}" alt="{doc_type}" class="img-thumbnail" style="max-height: {max_height}; object-fit: contain;">
            </a>
            '''
        link_label = "🔍 Open High-Res" if show_large_link else "🔍 View Full"
        cards += f"""
        <div class="border rounded p-2 bg-light text-center" style="min-width: 150px;">
            <span class="badge bg-secondary mb-1 d-block">{doc_type} (#{idx})</span>
            <div>{preview}</div>
            <div class="mt-1">
                <a href="{rx_url}" target="_blank" class="text-decoration-none small">{link_label}</a>
            </div>
        </div>
        """
    return f'<div class="mt-3 d-flex flex-wrap gap-2">{cards}</div>'


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session or 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def render_page(body_content, **kwargs):
    clinic_brand = session.get('clinic_name', 'ClinicDesk')
    role_mode = session.get('role_mode', 'doctor')
    nav_links = ""

    if 'user' in session and 'user_id' in session:
        revenue_nav = '<a href="/revenue" class="btn btn-outline-light btn-sm me-2">💰 Revenue Reports</a>' if role_mode == 'doctor' else ''
        mode_badge = (
            '<span class="badge bg-warning text-dark me-2">🖥️ Reception Mode</span>'
            if role_mode == 'reception'
            else '<span class="badge bg-light text-primary me-2">🩺 Doctor Mode</span>'
        )
        nav_links = f"""
            {mode_badge}
            <a href="/" class="btn btn-outline-light btn-sm me-2">Dashboard</a>
            <a href="/appointments" class="btn btn-outline-light btn-sm me-2">📅 Appointments</a>
            {revenue_nav}
            <a href="/search" class="btn btn-outline-light btn-sm me-2">Search Patients</a>
            <a href="/register" class="btn btn-outline-light btn-sm me-2">Register Patient</a>
            <a href="/logout" class="btn btn-danger btn-sm">Logout</a>
        """
    else:
        nav_links = """
            <a href="/login" class="btn btn-outline-light btn-sm me-2">Doctor Login</a>
            <a href="/signup" class="btn btn-light btn-sm text-primary fw-semibold">Register New Clinic</a>
        """

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{clinic_brand} | ClinicDesk SaaS</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="bg-light">
        <nav class="navbar navbar-dark bg-primary shadow-sm mb-4">
            <div class="container">
                <a class="navbar-brand fw-bold" href="/">🏥 {clinic_brand}</a>
                <div class="d-flex align-items-center flex-wrap gap-1">
                    {nav_links}
                </div>
            </div>
        </nav>
        <div class="container mb-5">
            {body_content}
        </div>
    </body>
    </html>
    """
    return render_template_string(html, **kwargs)


@app.route('/switch-mode', methods=['POST'])
@login_required
def switch_mode():
    uid = session['user_id']
    target_mode = request.form.get('target_mode', 'reception')

    if target_mode == 'reception':
        session['role_mode'] = 'reception'
        return redirect(url_for('index'))

    if target_mode == 'doctor':
        entered_pin = (request.form.get('doctor_pin') or '').strip()
        info = get_clinic_info(uid)
        if entered_pin == info['doctor_pin']:
            session['role_mode'] = 'doctor'
            return redirect(url_for('index'))
        return redirect(url_for('index', pin_error='1'))

    if target_mode == 'update_pin':
        if session.get('role_mode', 'doctor') != 'doctor':
            return redirect(url_for('index', pin_error='1'))
        new_pin = (request.form.get('new_pin') or '').strip()
        if len(new_pin) == 4 and new_pin.isdigit():
            try:
                supabase.table('clinics').update({"doctor_pin": new_pin}).eq('user_id', uid).execute()
                return redirect(url_for('index', pin_saved='1'))
            except Exception:
                pass
        return redirect(url_for('index', pin_error='2'))

    return redirect(url_for('index'))


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    error = None
    if request.method == 'POST':
        clinic_name = request.form.get('clinic_name', '').strip()
        doctor_name = request.form.get('doctor_name', '').strip()
        phone = request.form.get('phone', '').strip()
        doctor_pin = (request.form.get('doctor_pin') or '1234').strip()
        if not (len(doctor_pin) == 4 and doctor_pin.isdigit()):
            doctor_pin = '1234'
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        try:
            response = supabase.auth.sign_up({
                "email": email,
                "password": password
            })
            if response.user:
                user_id = str(response.user.id)
                supabase.table('clinics').insert({
                    "user_id": user_id,
                    "clinic_name": clinic_name,
                    "doctor_name": doctor_name,
                    "phone": phone,
                    "doctor_pin": doctor_pin
                }).execute()

                if response.session:
                    session['user'] = email
                    session['user_id'] = user_id
                    session['clinic_name'] = clinic_name
                    session['doctor_name'] = doctor_name
                    session['role_mode'] = 'doctor'
                    return redirect(url_for('index'))
                else:
                    return redirect(url_for('login', registered='1'))
            else:
                error = "Unable to create account. Please check your details and try again."
        except Exception as e:
            error = f"Registration failed: {str(e)}"

    body = f"""
    <div class="row justify-content-center mt-4">
        <div class="col-md-6">
            <div class="card shadow-sm p-4">
                <h3 class="mb-2 text-primary text-center">🏥 Register New Clinic Account</h3>
                <p class="text-muted text-center small mb-4">Create an isolated workspace for your clinic's patients, appointments & AI scans.</p>
                {f'<div class="alert alert-danger">{error}</div>' if error else ''}
                <form method="POST">
                    <div class="mb-3">
                        <label class="form-label">Clinic / Hospital Name</label>
                        <input type="text" name="clinic_name" class="form-control" placeholder="e.g. Sharma Polyclinic & Diagnostics" required>
                    </div>
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Doctor Full Name</label>
                            <input type="text" name="doctor_name" class="form-control" placeholder="e.g. Dr. R. K. Sharma" required>
                        </div>
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Clinic Phone Number</label>
                            <input type="text" name="phone" class="form-control" placeholder="e.g. 981020XXXX" required>
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Login Email</label>
                        <input type="email" name="email" class="form-control" required>
                    </div>
                    <div class="row">
                        <div class="col-md-7 mb-3">
                            <label class="form-label">Create Password (Min 6 characters)</label>
                            <input type="password" name="password" class="form-control" minlength="6" required>
                        </div>
                        <div class="col-md-5 mb-3">
                            <label class="form-label">4-Digit Doctor PIN</label>
                            <input type="text" name="doctor_pin" class="form-control" maxlength="4" pattern="[0-9]{{4}}" value="1234" required>
                            <div class="form-text">Used to unlock Revenue from Reception Mode.</div>
                        </div>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Create Clinic Workspace</button>
                </form>
                <div class="text-center mt-3 small">
                    Already have a clinic account? <a href="/login">Login here</a>
                </div>
            </div>
        </div>
    </div>
    """
    return render_page(body)


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    registered = request.args.get('registered')
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        try:
            response = supabase.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            if response.user:
                user_id = str(response.user.id)
                info = get_clinic_info(user_id)
                session['user'] = email
                session['user_id'] = user_id
                session['clinic_name'] = info['clinic_name']
                session['doctor_name'] = info['doctor_name']
                session['role_mode'] = 'doctor'
                return redirect(url_for('index'))
        except Exception:
            error = "Invalid email or password. Please verify your credentials."

    body = f"""
    <div class="row justify-content-center mt-5">
        <div class="col-md-5">
            <div class="card shadow-sm p-4">
                <h3 class="mb-3 text-primary text-center">🏥 ClinicDesk Login</h3>
                {'<div class="alert alert-success">Clinic account created! Please log in below.</div>' if registered else ''}
                {f'<div class="alert alert-danger">{error}</div>' if error else ''}
                <form method="POST">
                    <div class="mb-3">
                        <label class="form-label">Doctor / Staff Email</label>
                        <input type="email" name="email" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Password</label>
                        <input type="password" name="password" class="form-control" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Login to ClinicDesk</button>
                </form>
                <div class="text-center mt-3 small">
                    New clinic or doctor? <a href="/signup">Register a new clinic account</a>
                </div>
            </div>
        </div>
    </div>
    """
    return render_page(body)


@app.route('/logout')
def logout():
    session.clear()
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    uid = session['user_id']
    clinic_name = session.get('clinic_name', 'ClinicDesk')
    doctor_name = session.get('doctor_name', 'Doctor')
    role_mode = session.get('role_mode', 'doctor')
    pin_error = request.args.get('pin_error')
    pin_saved = request.args.get('pin_saved')

    try:
        p_res = supabase.table('patients').select('id', count='exact').eq('user_id', uid).execute()
        total_patients = p_res.count if p_res.count is not None else len(p_res.data)
    except Exception:
        total_patients = 0

    try:
        v_res = supabase.table('visits').select('id, consultation_fee, payment_status').eq('user_id', uid).execute()
        visits_data = v_res.data if v_res.data else []
        total_visits = len(visits_data)
        total_revenue = sum([float(v.get('consultation_fee') or 0) for v in visits_data if v.get('payment_status') == 'Paid'])
    except Exception:
        total_visits = 0
        total_revenue = 0

    today_str = str(date.today())
    try:
        a_res = supabase.table('appointments').select('id', count='exact').eq('user_id', uid).eq('appointment_date', today_str).execute()
        today_appts = a_res.count if a_res.count is not None else len(a_res.data)
    except Exception:
        today_appts = 0

    try:
        recent_res = supabase.table('patients').select('*').eq('user_id', uid).order('created_at', desc=True).limit(5).execute()
        recent_patients = recent_res.data if recent_res.data else []
    except Exception:
        recent_patients = []

    recent_rows = ""
    if recent_patients:
        for p in recent_patients:
            abha_badge = f'<span class="badge bg-light text-dark border">{p["abha_id"]}</span>' if p.get('abha_id') else '<span class="text-muted small">—</span>'
            recent_rows += f"""
            <tr>
                <td>{p['name']}</td>
                <td>{p['phone']}</td>
                <td>{abha_badge}</td>
                <td>{p.get('age', 'N/A')}</td>
                <td><a href="/patient/{p['id']}" class="btn btn-sm btn-outline-primary">View Profile</a></td>
            </tr>
            """
    else:
        recent_rows = '<tr><td colspan="5" class="text-center text-muted py-3">No recent patients registered yet.</td></tr>'

    # Role-based Workspace Switcher Banner
    if role_mode == 'doctor':
        mode_switcher_card = """
        <div class="card shadow-sm border-primary mb-4">
            <div class="card-body py-3 d-flex justify-content-between align-items-center flex-wrap gap-3">
                <div>
                    <span class="badge bg-primary me-2">🩺 Solo Clinic / Doctor Mode Active</span>
                    <span class="text-muted small">Full access enabled (including Revenue Reports & PIN settings). Handing the screen to front-desk staff?</span>
                </div>
                <div class="d-flex align-items-center gap-2 flex-wrap">
                    <form method="POST" action="/switch-mode" class="d-flex align-items-center gap-1">
                        <input type="hidden" name="target_mode" value="update_pin">
                        <input type="text" name="new_pin" maxlength="4" pattern="[0-9]{4}" class="form-control form-control-sm" style="width: 95px;" placeholder="New PIN">
                        <button type="submit" class="btn btn-sm btn-outline-secondary">Set PIN</button>
                    </form>
                    <form method="POST" action="/switch-mode" class="m-0">
                        <input type="hidden" name="target_mode" value="reception">
                        <button type="submit" class="btn btn-sm btn-warning fw-semibold">🖥️ Switch to Reception Mode</button>
                    </form>
                </div>
            </div>
        </div>
        """
        revenue_stat_card = f"""
        <div class="col-md-3">
            <div class="card shadow-sm border-0 bg-dark text-white p-3">
                <div class="card-body">
                    <h6 class="text-uppercase fw-semibold mb-2">Collected Revenue</h6>
                    <h2 class="display-5 fw-bold mb-0">₹{total_revenue:,.0f}</h2>
                </div>
            </div>
        </div>
        """
        revenue_quick_btn = '<a href="/revenue" class="btn btn-outline-dark">💰 View Financial Reports</a>'
    else:
        mode_switcher_card = """
        <div class="card shadow-sm border-warning bg-warning-subtle mb-4">
            <div class="card-body py-3 d-flex justify-content-between align-items-center flex-wrap gap-3">
                <div>
                    <span class="badge bg-warning text-dark me-2">🖥️ Reception / Front-Desk Mode Active</span>
                    <span class="text-dark small">Queue, Patient Registration & AI Scan Uploads are active. Financial totals are hidden.</span>
                </div>
                <form method="POST" action="/switch-mode" class="d-flex align-items-center gap-2 m-0">
                    <input type="hidden" name="target_mode" value="doctor">
                    <input type="password" name="doctor_pin" maxlength="4" class="form-control form-control-sm" style="width: 120px;" placeholder="Doctor PIN" required>
                    <button type="submit" class="btn btn-sm btn-primary fw-semibold">🔓 Unlock Doctor Mode</button>
                </form>
            </div>
        </div>
        """
        revenue_stat_card = """
        <div class="col-md-3">
            <div class="card shadow-sm border-0 bg-secondary text-white p-3">
                <div class="card-body">
                    <h6 class="text-uppercase fw-semibold mb-2">Revenue Ledger</h6>
                    <h2 class="display-5 fw-bold mb-0">🔒 Hidden</h2>
                </div>
            </div>
        </div>
        """
        revenue_quick_btn = ""

    alert_banner = ""
    if pin_error == '1':
        alert_banner = '<div class="alert alert-danger py-2">❌ Incorrect Doctor PIN. Default PIN is <strong>1234</strong> unless changed by the doctor.</div>'
    elif pin_error == '2':
        alert_banner = '<div class="alert alert-danger py-2">❌ Please enter a valid 4-digit numeric PIN.</div>'
    elif pin_saved == '1':
        alert_banner = '<div class="alert alert-success py-2">✅ Doctor PIN updated successfully!</div>'

    body = f"""
    <div class="row mb-3">
        <div class="col-md-12">
            <h2 class="fw-bold text-primary">🏥 {clinic_name} — Workspace Dashboard</h2>
            <p class="text-muted mb-2">Welcome back, <strong>{doctor_name}</strong>! Live operational overview for today ({today_str}).</p>
            {alert_banner}
        </div>
    </div>

    {mode_switcher_card}

    <div class="row g-4 mb-4">
        <div class="col-md-3">
            <div class="card shadow-sm border-0 bg-primary text-white p-3">
                <div class="card-body">
                    <h6 class="text-uppercase fw-semibold mb-2">Total Patients</h6>
                    <h2 class="display-5 fw-bold mb-0">{total_patients}</h2>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card shadow-sm border-0 bg-success text-white p-3">
                <div class="card-body">
                    <h6 class="text-uppercase fw-semibold mb-2">Today's Appts</h6>
                    <h2 class="display-5 fw-bold mb-0">{today_appts}</h2>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card shadow-sm border-0 bg-info text-white p-3">
                <div class="card-body">
                    <h6 class="text-uppercase fw-semibold mb-2">Consultations</h6>
                    <h2 class="display-5 fw-bold mb-0">{total_visits}</h2>
                </div>
            </div>
        </div>
        {revenue_stat_card}
    </div>

    <div class="row g-4">
        <div class="col-md-4">
            <div class="card shadow-sm p-4 h-100">
                <h5 class="text-primary mb-3">⚡ Quick Actions</h5>
                <div class="d-grid gap-2">
                    <a href="/appointments" class="btn btn-outline-primary">📅 View Today's Queue</a>
                    {revenue_quick_btn}
                    <a href="/register" class="btn btn-primary">➕ Register New Patient</a>
                </div>
            </div>
        </div>
        <div class="col-md-8">
            <div class="card shadow-sm h-100">
                <div class="card-header bg-white py-3">
                    <h5 class="mb-0 text-primary">Recent Patient Registrations</h5>
                </div>
                <div class="card-body p-0">
                    <table class="table table-hover mb-0 align-middle">
                        <thead class="table-light">
                            <tr>
                                <th>Name</th>
                                <th>Phone</th>
                                <th>ABHA ID</th>
                                <th>Age</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            {recent_rows}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    """
    return render_page(body)


@app.route('/revenue')
@login_required
def revenue_reports():
    if session.get('role_mode', 'doctor') != 'doctor':
        return redirect(url_for('index', pin_error='1'))

    uid = session['user_id']
    try:
        res = supabase.table('visits').select('*, patients(id, name, phone)').eq('user_id', uid).order('created_at', desc=True).execute()
        visits = res.data if res.data else []
    except Exception:
        visits = []

    total_collected = sum([float(v.get('consultation_fee') or 0) for v in visits if v.get('payment_status') == 'Paid'])
    total_pending = sum([float(v.get('consultation_fee') or 0) for v in visits if v.get('payment_status') == 'Pending'])
    total_billed = total_collected + total_pending

    rows = ""
    if visits:
        for idx, v in enumerate(visits, 1):
            p_info = v.get('patients') or {}
            p_name = p_info.get('name', 'Unknown')
            p_phone = p_info.get('phone', 'N/A')
            p_id = p_info.get('id', '#')
            visit_date = v.get('visit_date', v.get('created_at', ''))[:10]
            fee = float(v.get('consultation_fee') or 0)
            status = v.get('payment_status', 'Paid')
            badge_class = "bg-success" if status == "Paid" else "bg-warning text-dark"

            rows += f"""
            <tr>
                <td class="fw-bold">#{idx}</td>
                <td>{visit_date}</td>
                <td><a href="/patient/{p_id}" class="text-decoration-none fw-bold">{p_name}</a> ({p_phone})</td>
                <td>{v.get('diagnosis_tags', 'General Consultation')}</td>
                <td class="fw-bold">₹{fee:,.0f}</td>
                <td><span class="badge {badge_class}">{status}</span></td>
            </tr>
            """
    else:
        rows = '<tr><td colspan="6" class="text-center py-4 text-muted">No financial transaction records found.</td></tr>'

    body = f"""
    <div class="row mb-4">
        <div class="col-md-8">
            <h2 class="fw-bold text-primary">💰 Financial Revenue & Billing Report</h2>
            <p class="text-muted">Detailed ledger of all consultation fees, payments collected, and pending dues.</p>
        </div>
        <div class="col-md-4 text-end">
            <button onclick="window.print()" class="btn btn-outline-primary">🖨️ Print / Save Report PDF</button>
        </div>
    </div>

    <div class="row g-4 mb-4">
        <div class="col-md-4">
            <div class="card shadow-sm border-0 bg-success text-white p-3">
                <div class="card-body">
                    <h6 class="text-uppercase fw-semibold mb-2">Total Collected (Paid)</h6>
                    <h2 class="display-6 fw-bold mb-0">₹{total_collected:,.0f}</h2>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card shadow-sm border-0 bg-warning text-dark p-3">
                <div class="card-body">
                    <h6 class="text-uppercase fw-semibold mb-2">Pending Dues</h6>
                    <h2 class="display-6 fw-bold mb-0">₹{total_pending:,.0f}</h2>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card shadow-sm border-0 bg-primary text-white p-3">
                <div class="card-body">
                    <h6 class="text-uppercase fw-semibold mb-2">Total Billed Volume</h6>
                    <h2 class="display-6 fw-bold mb-0">₹{total_billed:,.0f}</h2>
                </div>
            </div>
        </div>
    </div>

    <div class="card shadow-sm">
        <div class="card-header bg-white py-3">
            <h5 class="mb-0 text-primary">Consultation Ledger</h5>
        </div>
        <div class="card-body p-0">
            <div class="table-responsive">
                <table class="table table-hover align-middle mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>#</th>
                            <th>Date</th>
                            <th>Patient Name & Phone</th>
                            <th>Diagnosis / Notes</th>
                            <th>Fee Amount</th>
                            <th>Payment Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <style>
        @media print {{
            .navbar, .btn, .no-print {{ display: none !important; }}
            body {{ background: white !important; }}
        }}
    </style>
    """
    return render_page(body)


@app.route('/appointments', methods=['GET', 'POST'])
@login_required
def appointments_queue():
    uid = session['user_id']
    selected_date = request.args.get('date', str(date.today()))
    error = None
    success = None

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            patient_id = request.form.get('patient_id')
            appt_date = request.form.get('appointment_date')
            time_slot = request.form.get('time_slot')

            try:
                supabase.table('appointments').insert({
                    "user_id": uid,
                    "patient_id": int(patient_id),
                    "appointment_date": appt_date,
                    "time_slot": time_slot,
                    "status": "Waiting"
                }).execute()
                success = "Appointment added to queue successfully!"
            except Exception as e:
                error = f"Error adding appointment: {str(e)}"

        elif action == 'update_status':
            appt_id = request.form.get('appointment_id')
            new_status = request.form.get('status')
            try:
                supabase.table('appointments').update({"status": new_status}).eq('id', appt_id).eq('user_id', uid).execute()
            except Exception as e:
                error = f"Error updating status: {str(e)}"

    p_res = supabase.table('patients').select('id, name, phone').eq('user_id', uid).order('name').execute()
    patients = p_res.data if p_res.data else []

    a_res = supabase.table('appointments').select('*, patients(name, phone, id)').eq('user_id', uid).eq('appointment_date', selected_date).order('created_at').execute()
    appointments = a_res.data if a_res.data else []

    patient_options = "".join([f'<option value="{p["id"]}">{p["name"]} ({p["phone"]})</option>' for p in patients])

    rows = ""
    if appointments:
        for idx, a in enumerate(appointments, 1):
            p_info = a.get('patients') or {}
            p_name = p_info.get('name', 'Unknown')
            p_id = p_info.get('id', '#')
            status = a.get('status', 'Waiting')

            badge_color = "bg-warning text-dark"
            if status == "In Consultation":
                badge_color = "bg-info text-dark"
            elif status == "Completed":
                badge_color = "bg-success"
            elif status == "Cancelled":
                badge_color = "bg-danger"

            rows += f"""
            <tr>
                <td class="fw-bold">#{idx}</td>
                <td><a href="/patient/{p_id}" class="text-decoration-none fw-bold">{p_name}</a></td>
                <td>{a.get('time_slot', 'Walk-in')}</td>
                <td><span class="badge {badge_color}">{status}</span></td>
                <td>
                    <form method="POST" class="d-inline">
                        <input type="hidden" name="action" value="update_status">
                        <input type="hidden" name="appointment_id" value="{a['id']}">
                        <select name="status" onchange="this.form.submit()" class="form-select form-select-sm d-inline-block w-auto">
                            <option value="Waiting" {'selected' if status == 'Waiting' else ''}>Waiting</option>
                            <option value="In Consultation" {'selected' if status == 'In Consultation' else ''}>In Consultation</option>
                            <option value="Completed" {'selected' if status == 'Completed' else ''}>Completed</option>
                            <option value="Cancelled" {'selected' if status == 'Cancelled' else ''}>Cancelled</option>
                        </select>
                    </form>
                </td>
            </tr>
            """
    else:
        rows = '<tr><td colspan="5" class="text-center py-4 text-muted">No appointments scheduled for this date.</td></tr>'

    body = f"""
    <div class="row">
        <div class="col-md-12">
            <h3 class="mb-4">📅 Daily Appointment Queue</h3>
            {f'<div class="alert alert-success">{success}</div>' if success else ''}
            {f'<div class="alert alert-danger">{error}</div>' if error else ''}
        </div>

        <div class="col-md-8">
            <div class="card shadow-sm mb-4 p-3">
                <form method="GET" class="row g-3 align-items-center mb-3">
                    <div class="col-auto">
                        <label class="col-form-label fw-bold">Select Date:</label>
                    </div>
                    <div class="col-auto">
                        <input type="date" name="date" value="{selected_date}" class="form-control" onchange="this.form.submit()">
                    </div>
                </form>
                <div class="table-responsive">
                    <table class="table table-hover align-middle mb-0">
                        <thead class="table-light">
                            <tr>
                                <th>Token</th>
                                <th>Patient Name</th>
                                <th>Time Slot</th>
                                <th>Status</th>
                                <th>Update Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="col-md-4">
            <div class="card shadow-sm p-4">
                <h5 class="text-primary mb-3">➕ Schedule Appointment</h5>
                <form method="POST">
                    <input type="hidden" name="action" value="add">
                    <div class="mb-3">
                        <label class="form-label">Select Patient</label>
                        <select name="patient_id" class="form-select" required>
                            <option value="">-- Choose Patient --</option>
                            {patient_options}
                        </select>
                        <div class="form-text">Patient not listed? <a href="/register">Register here</a></div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Appointment Date</label>
                        <input type="date" name="appointment_date" value="{selected_date}" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Time / Slot</label>
                        <input type="text" name="time_slot" class="form-control" placeholder="e.g. 10:30 AM or Walk-In">
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Add to Queue</button>
                </form>
            </div>
        </div>
    </div>
    """
    return render_page(body)


@app.route('/register', methods=['GET', 'POST'])
@login_required
def register_patient():
    uid = session['user_id']
    error = None
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        abha_id = request.form.get('abha_id', '').strip()
        age = request.form.get('age')
        gender = request.form.get('gender')

        payload = {
            "user_id": uid,
            "name": name,
            "phone": phone,
            "age": int(age) if age else None,
            "gender": gender
        }
        if abha_id:
            payload["abha_id"] = abha_id

        try:
            response = supabase.table('patients').insert(payload).execute()

            if response.data:
                patient_id = response.data[0]['id']
                return redirect(url_for('patient_profile', patient_id=patient_id))
        except Exception as e:
            error = f"Error registering patient: {str(e)}"

    body = f"""
    <div class="row justify-content-center">
        <div class="col-md-6">
            <div class="card shadow-sm p-4">
                <h3 class="mb-3 text-primary">Register New Patient</h3>
                {f'<div class="alert alert-danger">{error}</div>' if error else ''}
                <form method="POST">
                    <div class="mb-3">
                        <label class="form-label">Patient Full Name</label>
                        <input type="text" name="name" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Phone Number (Unique ID)</label>
                        <input type="text" name="phone" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">ABHA Health ID (Optional - 14-Digit or @abdm)</label>
                        <input type="text" name="abha_id" class="form-control" placeholder="e.g. 91-1234-5678-9012 or name@abdm">
                        <div class="form-text">No ABHA ID yet? Patient can generate one free at <a href="https://abha.abdm.gov.in/abha/v3/register" target="_blank">abha.abdm.gov.in</a></div>
                    </div>
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Age</label>
                            <input type="number" name="age" class="form-control">
                        </div>
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Gender</label>
                            <select name="gender" class="form-select">
                                <option value="Male">Male</option>
                                <option value="Female">Female</option>
                                <option value="Other">Other</option>
                            </select>
                        </div>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Save & Continue</button>
                </form>
            </div>
        </div>
    </div>
    """
    return render_page(body)


@app.route('/search', methods=['GET'])
@login_required
def search_patients():
    uid = session['user_id']
    query = request.args.get('q', '')
    patients = []
    if query:
        res = (
            supabase.table('patients')
            .select('*')
            .eq('user_id', uid)
            .or_(f"name.ilike.%{query}%,phone.ilike.%{query}%,abha_id.ilike.%{query}%")
            .execute()
        )
        patients = res.data
    else:
        res = supabase.table('patients').select('*').eq('user_id', uid).order('created_at', desc=True).limit(15).execute()
        patients = res.data

    rows = ""
    if patients:
        for p in patients:
            abha_val = p.get('abha_id') or '—'
            rows += f"""
            <tr>
                <td class="fw-semibold">{p['name']}</td>
                <td>{p['phone']}</td>
                <td><span class="badge bg-light text-dark border">{abha_val}</span></td>
                <td>{p.get('age', '')}</td>
                <td>{p.get('gender', '')}</td>
                <td><a href="/patient/{p['id']}" class="btn btn-sm btn-outline-primary">View Profile</a></td>
            </tr>
            """
    else:
        rows = '<tr><td colspan="6" class="text-center py-4 text-muted">No patients found.</td></tr>'

    body = f"""
    <div class="row justify-content-center">
        <div class="col-md-10">
            <h3 class="mb-4">Patient Directory & Search</h3>
            <form method="GET" class="input-group mb-4">
                <input type="text" name="q" value="{query}" class="form-control" placeholder="Search by name, phone number, or ABHA ID...">
                <button class="btn btn-primary" type="submit">Search</button>
            </form>
            <div class="card shadow-sm">
                <div class="card-body p-0">
                    <table class="table table-hover mb-0 align-middle">
                        <thead class="table-light">
                            <tr>
                                <th>Name</th>
                                <th>Phone</th>
                                <th>ABHA ID</th>
                                <th>Age</th>
                                <th>Gender</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    """
    return render_page(body)


@app.route('/patient/<int:patient_id>', methods=['GET', 'POST'])
@login_required
def patient_profile(patient_id):
    uid = session['user_id']
    if request.method == 'POST' and request.form.get('action') == 'update_abha':
        new_abha = request.form.get('abha_id', '').strip()
        try:
            supabase.table('patients').update({"abha_id": new_abha or None}).eq('id', patient_id).eq('user_id', uid).execute()
        except Exception:
            pass
        return redirect(url_for('patient_profile', patient_id=patient_id))

    p_res = supabase.table('patients').select('*').eq('id', patient_id).eq('user_id', uid).execute()
    if not p_res.data:
        return "Patient not found or unauthorized access.", 404
    patient = p_res.data[0]

    v_res = supabase.table('visits').select('*, prescriptions(*)').eq('patient_id', patient_id).order('created_at', desc=True).execute()
    visits = v_res.data or []

    today_str = str(date.today())
    todays_visit = next((v for v in visits if str(v.get('visit_date', v.get('created_at', '')))[:10] == today_str), None)

    token = generate_share_token(patient['id'], patient['phone'])
    share_url = url_for('public_patient_share', patient_id=patient['id'], token=token, _external=True)
    wa_phone = format_whatsapp_phone(patient['phone'])
    clinic_name = session.get('clinic_name', 'ClinicDesk')
    wa_message = (
        f"Hello {patient['name']},\n"
        f"Here is your digital medical record & scan summary from {clinic_name}. "
        f"You can view or share this link with any doctor for a second opinion:\n{share_url}"
    )
    wa_link = f"https://wa.me/{wa_phone}?text={urllib.parse.quote(wa_message)}"

    visit_cards = ""
    if visits:
        for v in visits:
            visit_date = v.get('visit_date', v.get('created_at', ''))[:10]
            fee = v.get('consultation_fee', 0)
            pay_status = v.get('payment_status', 'Paid')
            pay_badge = "bg-success" if pay_status == "Paid" else "bg-warning text-dark"

            rx_list = v.get('prescriptions') or []
            rx_section = render_attachments_gallery(rx_list, max_height="140px", show_large_link=False)

            visit_cards += f"""
            <div class="card shadow-sm mb-3">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
                        <h6 class="text-primary fw-bold mb-0">Visit Date: {visit_date}</h6>
                        <div>
                            <span class="badge bg-dark me-1">Fee: ₹{fee}</span>
                            <span class="badge {pay_badge} me-2">{pay_status}</span>
                            <span class="badge bg-info text-dark">{v.get('diagnosis_tags', '')}</span>
                        </div>
                    </div>
                    <p class="mt-2 mb-2" style="white-space: pre-line;"><strong>Notes:</strong> {v.get('notes', 'No notes recorded.')}</p>
                    {rx_section}
                    <div class="mt-3 pt-2 border-top d-flex justify-content-end">
                        <a href="/visit/{v['id']}/add-report" class="btn btn-sm btn-outline-primary">➕ Add Another Report / Scan to This Visit</a>
                    </div>
                </div>
            </div>
            """
    else:
        visit_cards = '<div class="alert alert-info text-center">No consultation history recorded yet.</div>'

    abha_display = patient.get('abha_id') or ''
    attach_today_btn = (
        f'<a href="/visit/{todays_visit["id"]}/add-report" class="btn btn-primary w-100 mb-2">📎 Add Report to Today\'s Visit (No Extra Fee)</a>'
        if todays_visit else ''
    )
    new_visit_btn_class = "btn btn-outline-success w-100 mb-2" if todays_visit else "btn btn-success w-100 mb-2"

    body = f"""
    <div class="row">
        <div class="col-md-4">
            <div class="card shadow-sm p-4 mb-4">
                <h4 class="text-primary">{patient['name']}</h4>
                <p class="mb-1"><strong>Phone:</strong> {patient['phone']}</p>
                <p class="mb-1"><strong>Age:</strong> {patient.get('age', '')} | <strong>Gender:</strong> {patient.get('gender', '')}</p>
                
                <form method="POST" class="mt-2 mb-3 p-2 bg-light rounded border">
                    <input type="hidden" name="action" value="update_abha">
                    <label class="form-label small fw-bold mb-1 text-secondary">🇮🇳 ABHA Health ID</label>
                    <div class="input-group input-group-sm">
                        <input type="text" name="abha_id" value="{abha_display}" class="form-control" placeholder="14-digit ABHA ID">
                        <button type="submit" class="btn btn-outline-primary">Save</button>
                    </div>
                </form>

                {attach_today_btn}
                <a href="/visit/new/{patient['id']}" class="{new_visit_btn_class}">🩺 Log New Visit, Scans & Fee</a>
                <a href="{wa_link}" target="_blank" class="btn btn-outline-success w-100 mb-2">📲 Share Records on WhatsApp</a>
                <button type="button" onclick="copyShareLink()" class="btn btn-outline-primary w-100 mb-2">🔗 Copy Second-Opinion Link</button>
                <a href="/patient/{patient['id']}/print" target="_blank" class="btn btn-outline-secondary w-100">🖨️ Print / Save PDF Summary</a>
                <div id="copyAlert" class="text-success small mt-2 text-center fw-semibold" style="display:none;">✅ Second-opinion link copied!</div>
            </div>
        </div>
        <div class="col-md-8">
            <h4 class="mb-3">Consultation History & Billing</h4>
            {visit_cards}
        </div>
    </div>
    <script>
        function copyShareLink() {{
            navigator.clipboard.writeText("{share_url}");
            document.getElementById("copyAlert").style.display = "block";
            setTimeout(() => {{ document.getElementById("copyAlert").style.display = "none"; }}, 3000);
        }}
    </script>
    """
    return render_page(body)


@app.route('/visit/<int:visit_id>/add-report', methods=['GET', 'POST'])
@login_required
def add_report_to_visit(visit_id):
    """Attaches one or more extra scans/reports to an existing visit without duplicating the visit or fee."""
    uid = session.get('user_id')
    if not uid:
        return redirect(url_for('logout'))

    try:
        v_res = supabase.table('visits').select('*, patients(id, name)').eq('id', visit_id).eq('user_id', uid).execute()
        if not v_res.data:
            return "Visit not found or unauthorized access.", 404
        visit = v_res.data[0]
        patient_info = visit.get('patients') or {}
        patient_id = patient_info.get('id') or visit.get('patient_id')
        patient_name = patient_info.get('name', 'Patient')
    except Exception as e:
        return f"<div style='padding:20px;font-family:sans-serif;'><h3>Database Error</h3><p>{str(e)}</p><a href='/'>Back to Dashboard</a></div>", 500

    error = None
    if request.method == 'POST':
        document_type = request.form.get('document_type', 'Lab Report')
        files = request.files.getlist('prescription_files')
        use_ai_ocr = request.form.get('use_ai_ocr')

        valid_files = [f for f in files if f and f.filename != '']
        if not valid_files:
            error = "Please choose at least one report or scan file to attach."
        else:
            try:
                existing_notes = (visit.get('notes') or '').strip()
                existing_diag = (visit.get('diagnosis_tags') or '').strip()
                appended_notes = []

                for idx, file in enumerate(valid_files, 1):
                    raw_bytes = file.read()
                    raw_mime = file.content_type or 'image/jpeg'
                    file_bytes, mime_type = compress_image_for_ocr(raw_bytes, raw_mime)

                    if use_ai_ocr and file_bytes:
                        ai_diag, ai_notes = extract_medical_file_with_ai(file_bytes, mime_type, document_type)
                        if not existing_diag or existing_diag == "General Consultation":
                            existing_diag = ai_diag
                        appended_notes.append(f"--- Additional {document_type} (#{idx}: {file.filename}) ---\n{ai_notes}")

                    filename = secure_filename(file.filename) or f"report_{idx}.jpg"
                    file_path = f"visit_{visit_id}_{int(time.time())}_{idx}_{filename}"

                    supabase.storage.from_('prescriptions').upload(
                        file_path, file_bytes, {"content-type": mime_type}
                    )
                    public_url = supabase.storage.from_('prescriptions').get_public_url(file_path)

                    supabase.table('prescriptions').insert({
                        "visit_id": visit_id,
                        "prescription_url": public_url,
                        "document_type": document_type
                    }).execute()

                if appended_notes:
                    joined_new = "\n\n".join(appended_notes)
                    updated_notes = f"{existing_notes}\n\n{joined_new}" if existing_notes else joined_new
                    supabase.table('visits').update({
                        "diagnosis_tags": existing_diag,
                        "notes": updated_notes
                    }).eq('id', visit_id).eq('user_id', uid).execute()

                return redirect(url_for('patient_profile', patient_id=patient_id))
            except Exception as e:
                error = f"Error attaching report: {str(e)}"

    visit_date = visit.get('visit_date', visit.get('created_at', ''))[:10]

    body = f"""
    <div class="row justify-content-center">
        <div class="col-md-7">
            <div class="card shadow-sm p-4">
                <h3 class="mb-1 text-primary">➕ Add Reports / Scans to Existing Visit</h3>
                <p class="text-muted small mb-3">Patient: <strong>{patient_name}</strong> | Visit Date: <strong>{visit_date}</strong> (No extra fee will be charged)</p>
                {f'<div class="alert alert-danger">{error}</div>' if error else ''}
                <form method="POST" enctype="multipart/form-data">
                    <div class="mb-3">
                        <label class="form-label">Document Type</label>
                        <select name="document_type" class="form-select">
                            <option value="Lab Report">Blood / Lab Report</option>
                            <option value="Ultrasound">Ultrasound / Echo</option>
                            <option value="X-Ray">X-Ray / Bone Scan</option>
                            <option value="MRI">MRI / CT Scan</option>
                            <option value="Prescription">Prescription</option>
                        </select>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Select One or Multiple Files (Images / PDFs)</label>
                        <input type="file" name="prescription_files" class="form-control" accept="image/*,.pdf" multiple required>
                        <div class="form-text">Hold <strong>Ctrl</strong> (or select multiple photos on phone) to attach all pages/reports at once.</div>
                        <div class="form-check mt-2">
                            <input class="form-check-input" type="checkbox" name="use_ai_ocr" id="use_ai_ocr" value="1" checked>
                            <label class="form-check-label fw-semibold text-success" for="use_ai_ocr">
                                🤖 Extract & Append Findings with Gemini AI Vision
                            </label>
                        </div>
                    </div>
                    <div class="d-flex gap-2">
                        <a href="/patient/{patient_id}" class="btn btn-outline-secondary w-50">Cancel</a>
                        <button type="submit" class="btn btn-primary w-50">Attach Reports to Visit</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    """
    return render_page(body)


@app.route('/share/<int:patient_id>/<token>')
def public_patient_share(patient_id, token):
    """Public read-only patient medical record & scan portal for second opinions (no login required)."""
    p_res = supabase.table('patients').select('*').eq('id', patient_id).execute()
    if not p_res.data:
        return "Record not found", 404
    patient = p_res.data[0]

    expected_token = generate_share_token(patient['id'], patient['phone'])
    if not hmac.compare_digest(token, expected_token):
        return "Invalid or expired share link.", 403

    clinic_info = get_clinic_info(patient.get('user_id'))
    v_res = supabase.table('visits').select('*, prescriptions(*)').eq('patient_id', patient_id).order('created_at', desc=True).execute()
    visits = v_res.data

    visit_cards = ""
    if visits:
        for v in visits:
            visit_date = v.get('visit_date', v.get('created_at', ''))[:10]
            rx_list = v.get('prescriptions') or []
            rx_section = render_attachments_gallery(rx_list, max_height="200px", show_large_link=True)

            visit_cards += f"""
            <div class="card shadow-sm mb-3">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-center">
                        <h6 class="text-primary fw-bold mb-0">Consultation Date: {visit_date}</h6>
                        <span class="badge bg-info text-dark">{v.get('diagnosis_tags', 'Consultation')}</span>
                    </div>
                    <p class="mt-2 mb-2" style="white-space: pre-line;"><strong>Clinical Summary & Notes:</strong> {v.get('notes', 'No notes recorded.')}</p>
                    {rx_section}
                </div>
            </div>
            """
    else:
        visit_cards = '<div class="alert alert-info">No consultation records available yet.</div>'

    abha_line = f"<p class='mb-0'><strong>ABHA Health ID:</strong> {patient['abha_id']}</p>" if patient.get('abha_id') else ""

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Patient Medical Records - {patient['name']}</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="bg-light">
        <nav class="navbar navbar-dark bg-primary shadow-sm mb-4">
            <div class="container">
                <span class="navbar-brand fw-bold">🏥 {clinic_info['clinic_name']} — Digital Health Record</span>
                <button onclick="window.print()" class="btn btn-outline-light btn-sm">🖨️ Print / Save PDF</button>
            </div>
        </nav>
        <div class="container mb-5" style="max-width: 850px;">
            <div class="card shadow-sm p-4 mb-4 border-primary">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <h3 class="text-primary mb-1">{patient['name']}</h3>
                        <p class="mb-1"><strong>Age:</strong> {patient.get('age', 'N/A')} | <strong>Gender:</strong> {patient.get('gender', 'N/A')}</p>
                        {abha_line}
                    </div>
                    <div class="text-end">
                        <span class="badge bg-success mb-1">Verified Digital Record</span>
                        <div class="small text-muted">Consulting: {clinic_info['doctor_name']}</div>
                    </div>
                </div>
            </div>
            <h5 class="mb-3 text-secondary">Medical History, Prescriptions & Diagnostic Scans</h5>
            {visit_cards}
        </div>
    </body>
    </html>
    """
    return html


@app.route('/patient/<int:patient_id>/print')
@login_required
def print_patient_summary(patient_id):
    uid = session['user_id']
    clinic_name = session.get('clinic_name', 'ClinicDesk')
    doctor_name = session.get('doctor_name', 'Doctor')

    p_res = supabase.table('patients').select('*').eq('id', patient_id).eq('user_id', uid).execute()
    if not p_res.data:
        return "Patient not found", 404
    patient = p_res.data[0]

    v_res = supabase.table('visits').select('*, prescriptions(*)').eq('patient_id', patient_id).order('created_at', desc=True).execute()
    visits = v_res.data

    visit_rows = ""
    if visits:
        for v in visits:
            visit_date = v.get('visit_date', v.get('created_at', ''))[:10]
            fee = v.get('consultation_fee', 0)
            pay_status = v.get('payment_status', 'Paid')
            rx_html = ""
            for idx, rx in enumerate(v.get('prescriptions') or [], 1):
                rx_url = rx['prescription_url']
                doc_type = rx.get('document_type', 'Prescription')
                if not rx_url.lower().endswith('.pdf'):
                    rx_html += f'<div style="display:inline-block; margin: 10px 10px 0 0; vertical-align:top;"><p class="mb-1"><strong>[{doc_type} #{idx}]</strong></p><img src="{rx_url}" style="max-width: 240px; border: 1px solid #ccc; padding: 4px;" alt="Scan"></div>'
                else:
                    rx_html += f'<div style="margin-top: 8px;"><p class="mb-1"><strong>[{doc_type} #{idx}]</strong> - <a href="{rx_url}" target="_blank">View PDF Document</a></p></div>'

            visit_rows += f"""
            <div style="border-bottom: 1px solid #ddd; padding-bottom: 15px; margin-bottom: 15px;">
                <p><strong>Date:</strong> {visit_date} | <strong>Diagnosis:</strong> {v.get('diagnosis_tags', 'N/A')} | <strong>Fee:</strong> ₹{fee} ({pay_status})</p>
                <p style="white-space: pre-line;"><strong>Notes:</strong> {v.get('notes', 'No notes.')}</p>
                <div>{rx_html}</div>
            </div>
            """
    else:
        visit_rows = "<p>No visit history recorded.</p>"

    abha_print = f"<div class='col-md-12 mt-2'><strong>ABHA ID:</strong> {patient['abha_id']}</div>" if patient.get('abha_id') else ""

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Patient Medical & Billing Summary - {patient['name']}</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            @media print {{
                .no-print {{ display: none !important; }}
                body {{ background: white !important; font-size: 14px; }}
            }}
        </style>
    </head>
    <body class="bg-white p-5" onload="window.print()">
        <div class="container">
            <div class="d-flex justify-content-between align-items-center border-bottom pb-3 mb-4">
                <div>
                    <h2>🏥 {clinic_name} — Patient Summary</h2>
                    <p class="text-muted mb-0">Attending Physician: {doctor_name} | Powered by ClinicDesk</p>
                </div>
                <button onclick="window.print()" class="btn btn-primary no-print">🖨️ Print / Save PDF</button>
            </div>

            <div class="card p-3 mb-4 bg-light border-0">
                <h4 class="text-primary">{patient['name']}</h4>
                <div class="row">
                    <div class="col-md-4"><strong>Phone:</strong> {patient['phone']}</div>
                    <div class="col-md-4"><strong>Age:</strong> {patient.get('age', 'N/A')}</div>
                    <div class="col-md-4"><strong>Gender:</strong> {patient.get('gender', 'N/A')}</div>
                    {abha_print}
                </div>
            </div>

            <h4 class="mb-3">Visit, Prescription, Scan & Billing History</h4>
            {visit_rows}
        </div>
    </body>
    </html>
    """
    return html


@app.route('/visit/new/<int:patient_id>', methods=['GET', 'POST'])
@login_required
def log_visit(patient_id):
    uid = session.get('user_id')
    if not uid:
        return redirect(url_for('logout'))

    try:
        p_res = supabase.table('patients').select('*').eq('id', patient_id).eq('user_id', uid).execute()
        if not p_res.data:
            return "Patient not found or unauthorized access.", 404
        patient = p_res.data[0]
        patient_name = patient['name']

        # Check if this patient already has a visit logged today
        v_check = supabase.table('visits').select('id, created_at, visit_date').eq('patient_id', patient_id).order('created_at', desc=True).limit(5).execute()
        today_str = str(date.today())
        todays_visit = next(
            (v for v in (v_check.data or []) if str(v.get('visit_date', v.get('created_at', '')))[:10] == today_str),
            None
        )
    except Exception as e:
        return f"<div style='padding:20px;font-family:sans-serif;'><h3>Database Error</h3><p>{str(e)}</p><a href='/'>Back to Dashboard</a></div>", 500

    error = None
    if request.method == 'POST':
        diagnosis = (request.form.get('diagnosis') or '').strip()
        notes = (request.form.get('notes') or '').strip()
        document_type = request.form.get('document_type', 'Prescription')
        fee = request.form.get('consultation_fee', 0)
        payment_status = request.form.get('payment_status', 'Paid')
        files = request.files.getlist('prescription_files')
        use_ai_ocr = request.form.get('use_ai_ocr')

        valid_files = [f for f in files if f and f.filename != '']

        try:
            processed_files = []
            ai_summaries = []

            for idx, file in enumerate(valid_files, 1):
                raw_bytes = file.read()
                raw_mime = file.content_type or 'image/jpeg'
                file_bytes, mime_type = compress_image_for_ocr(raw_bytes, raw_mime)
                processed_files.append((idx, file.filename, file_bytes, mime_type))

                if use_ai_ocr and file_bytes:
                    ai_diag, ai_notes = extract_medical_file_with_ai(file_bytes, mime_type, document_type)
                    if not diagnosis:
                        diagnosis = ai_diag
                    label = f"Report #{idx} ({file.filename})" if len(valid_files) > 1 else "AI OCR Extracted Report"
                    ai_summaries.append(f"--- {label} ---\n{ai_notes}")

            if ai_summaries:
                combined_ai = "\n\n".join(ai_summaries)
                notes = f"{notes}\n\n{combined_ai}" if notes else combined_ai

            v_res = supabase.table('visits').insert({
                "user_id": uid,
                "patient_id": patient_id,
                "diagnosis_tags": diagnosis or "General Consultation",
                "notes": notes,
                "consultation_fee": float(fee) if fee else 0,
                "payment_status": payment_status
            }).execute()

            if v_res.data and processed_files:
                visit_id = v_res.data[0]['id']
                for idx, orig_name, file_bytes, mime_type in processed_files:
                    filename = secure_filename(orig_name) or f"scan_{idx}.jpg"
                    file_path = f"visit_{visit_id}_{int(time.time())}_{idx}_{filename}"

                    supabase.storage.from_('prescriptions').upload(
                        file_path, file_bytes, {"content-type": mime_type}
                    )
                    public_url = supabase.storage.from_('prescriptions').get_public_url(file_path)

                    supabase.table('prescriptions').insert({
                        "visit_id": visit_id,
                        "prescription_url": public_url,
                        "document_type": document_type
                    }).execute()

            return redirect(url_for('patient_profile', patient_id=patient_id))
        except Exception as e:
            error = f"Error saving consultation: {str(e)}"

    same_day_warning = ""
    if todays_visit:
        same_day_warning = f"""
        <div class="alert alert-warning border-warning shadow-sm">
            <strong>⚠️ Same-Day Visit Detected:</strong> {patient_name} already has a visit logged today.<br>
            If the patient is simply handing over an extra report or scan from today's consultation,
            <a href="/visit/{todays_visit['id']}/add-report" class="alert-link fw-bold">click here to attach it to today's visit without charging a duplicate fee</a>.
        </div>
        """

    body = f"""
    <div class="row justify-content-center">
        <div class="col-md-7">
            <div class="card shadow-sm p-4">
                <h3 class="mb-3 text-primary">Log Visit, Scans & AI OCR for {patient_name}</h3>
                {same_day_warning}
                {f'<div class="alert alert-danger">{error}</div>' if error else ''}
                <form method="POST" enctype="multipart/form-data">
                    <div class="mb-3">
                        <label class="form-label">Primary Document Type</label>
                        <select name="document_type" class="form-select">
                            <option value="Prescription">Prescription</option>
                            <option value="Lab Report">Blood / Lab Report</option>
                            <option value="Ultrasound">Ultrasound / Echo</option>
                            <option value="X-Ray">X-Ray / Bone Scan</option>
                            <option value="MRI">MRI / CT Scan</option>
                        </select>
                        <div class="form-text">Selecting X-Ray, Ultrasound, or MRI automatically adds a preliminary radiologist verification reminder.</div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Upload One or Multiple Scan Images / PDF Reports</label>
                        <input type="file" name="prescription_files" id="prescription_files" class="form-control" accept="image/*,.pdf" multiple>
                        <div class="form-text">Select all reports for this visit together (hold <strong>Ctrl</strong> on PC or tap multiple photos on phone). You can also add more reports later from the visit card.</div>
                        <div class="form-check mt-2">
                            <input class="form-check-input" type="checkbox" name="use_ai_ocr" id="use_ai_ocr" value="1" checked>
                            <label class="form-check-label fw-semibold text-success" for="use_ai_ocr">
                                🤖 Automatically Extract Diagnosis & Notes from All Uploaded Reports
                            </label>
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Diagnosis / Symptoms (Optional if AI OCR is checked)</label>
                        <input type="text" name="diagnosis" class="form-control" placeholder="e.g. Fever, Gall bladder stone or let AI fill this">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Clinical Notes / Prescription Details</label>
                        <textarea name="notes" class="form-control" rows="3" placeholder="Add custom notes or leave for AI extraction..."></textarea>
                    </div>
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Consultation Fee (₹)</label>
                            <input type="number" name="consultation_fee" class="form-control" placeholder="500" value="500">
                        </div>
                        <div class="col-md-6 mb-3">
                            <label class="form-label">Payment Status</label>
                            <select name="payment_status" class="form-select">
                                <option value="Paid">Paid</option>
                                <option value="Pending">Pending</option>
                            </select>
                        </div>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Save Consultation & Process All Reports</button>
                </form>
            </div>
        </div>
    </div>
    """
    return render_page(body)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)