import os
import base64
import requests
from datetime import date
from functools import wraps
from flask import Flask, redirect, render_template_string, request, session, url_for
from supabase import Client, create_client
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "clinicdesk_secure_random_secret_key"

# ClinicDesk Supabase Credentials
SUPABASE_URL = "https://pfmldhpidblncypuagld.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBmbWxkaHBpZGJsbmN5cHVhZ2xkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTQ2NTM2MjEsImV4cCI6MjExMDIyOTYyMX0.SI7i2c5IeGwP3T3qi0GaCEPU-WUeRFP2T4oh0Ioun0c"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Gemini AI API Key Configuration (Python 3.7+ Compatible REST API)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")

def extract_medical_file_with_ai(file_bytes, mime_type):
    """Sends uploaded prescription or lab report to Gemini 1.5 Flash via REST API."""
    if GEMINI_API_KEY == "YOUR_GEMINI_API_KEY_HERE":
        return "AI API Key not configured.", "OCR skipped. Please configure GEMINI_API_KEY."
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        encoded_data = base64.b64encode(file_bytes).decode('utf-8')
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "You are an expert medical AI assistant. Analyze this attached medical document (prescription, lab report, or scan). "
                                "Return your analysis strictly in two sections:\n"
                                "DIAGNOSIS: [Briefly state suspected condition, symptoms, or test names]\n"
                                "NOTES: [Extract all medications, dosages, lab values, and doctor instructions clearly]"
                            )
                        },
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
        
        response = requests.post(url, json=payload, timeout=30)
        result = response.json()
        
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        diagnosis = "AI Extracted Report"
        notes = text
        
        if "DIAGNOSIS:" in text and "NOTES:" in text:
            parts = text.split("NOTES:")
            diag_part = parts[0].replace("DIAGNOSIS:", "").strip()
            if diag_part:
                diagnosis = diag_part[:100]
            notes = parts[1].strip()
            
        return diagnosis, notes
    except Exception as e:
        return "General Consultation", f"AI OCR Error: {str(e)}"

# Authentication Decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Single unified template wrapper
def render_page(body_content, **kwargs):
    nav_links = ""
    if 'user' in session:
        nav_links = f"""
            <a href="/" class="btn btn-outline-light btn-sm me-2">Dashboard</a>
            <a href="/appointments" class="btn btn-outline-light btn-sm me-2">📅 Appointments</a>
            <a href="/revenue" class="btn btn-outline-light btn-sm me-2">💰 Revenue Reports</a>
            <a href="/search" class="btn btn-outline-light btn-sm me-2">Search Patients</a>
            <a href="/register" class="btn btn-outline-light btn-sm me-2">Register Patient</a>
            <a href="/logout" class="btn btn-danger btn-sm">Logout</a>
        """
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>ClinicDesk SaaS</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="bg-light">
        <nav class="navbar navbar-dark bg-primary shadow-sm mb-4">
            <div class="container">
                <a class="navbar-brand fw-bold" href="/">🏥 ClinicDesk</a>
                <div>
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

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            response = supabase.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            if response.user:
                session['user'] = email
                return redirect(url_for('index'))
        except Exception:
            error = "Invalid email or password. Please verify your Supabase Auth credentials."

    body = f"""
    <div class="row justify-content-center mt-5">
        <div class="col-md-5">
            <div class="card shadow-sm p-4">
                <h3 class="mb-3 text-primary text-center">🏥 ClinicDesk Login</h3>
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
            </div>
        </div>
    </div>
    """
    return render_page(body)

@app.route('/logout')
def logout():
    session.pop('user', None)
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    try:
        p_res = supabase.table('patients').select('id', count='exact').execute()
        total_patients = p_res.count if p_res.count is not None else len(p_res.data)
    except Exception:
        total_patients = 0

    try:
        v_res = supabase.table('visits').select('id, consultation_fee, payment_status').execute()
        visits_data = v_res.data if v_res.data else []
        total_visits = len(visits_data)
        total_revenue = sum([float(v.get('consultation_fee') or 0) for v in visits_data if v.get('payment_status') == 'Paid'])
    except Exception:
        total_visits = 0
        total_revenue = 0

    today_str = str(date.today())
    try:
        a_res = supabase.table('appointments').select('id', count='exact').eq('appointment_date', today_str).execute()
        today_appts = a_res.count if a_res.count is not None else len(a_res.data)
    except Exception:
        today_appts = 0

    try:
        recent_res = supabase.table('patients').select('*').order('created_at', desc=True).limit(5).execute()
        recent_patients = recent_res.data if recent_res.data else []
    except Exception:
        recent_patients = []

    recent_rows = ""
    if recent_patients:
        for p in recent_patients:
            recent_rows += f"""
            <tr>
                <td>{p['name']}</td>
                <td>{p['phone']}</td>
                <td>{p.get('age', 'N/A')}</td>
                <td><a href="/patient/{p['id']}" class="btn btn-sm btn-outline-primary">View Profile</a></td>
            </tr>
            """
    else:
        recent_rows = '<tr><td colspan="4" class="text-center text-muted py-3">No recent patients registered.</td></tr>'

    body = f"""
    <div class="row mb-4">
        <div class="col-md-12">
            <h2 class="fw-bold text-primary">🏥 ClinicDesk Doctor Dashboard</h2>
            <p class="text-muted">Welcome back! Here is your clinic's live operational overview for today ({today_str}).</p>
        </div>
    </div>

    <!-- Metric Cards -->
    <div class="row g-4 mb-5">
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
        <div class="col-md-3">
            <div class="card shadow-sm border-0 bg-dark text-white p-3">
                <div class="card-body">
                    <h6 class="text-uppercase fw-semibold mb-2">Collected Revenue</h6>
                    <h2 class="display-5 fw-bold mb-0">₹{total_revenue:,.0f}</h2>
                </div>
            </div>
        </div>
    </div>

    <!-- Quick Actions & Recent Patients -->
    <div class="row g-4">
        <div class="col-md-4">
            <div class="card shadow-sm p-4 h-100">
                <h5 class="text-primary mb-3">⚡ Quick Actions</h5>
                <div class="d-grid gap-2">
                    <a href="/appointments" class="btn btn-outline-primary">📅 View Today's Queue</a>
                    <a href="/revenue" class="btn btn-outline-dark">💰 View Financial Reports</a>
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
    try:
        res = supabase.table('visits').select('*, patients(name, phone)').order('created_at', desc=True).execute()
        visits = res.data if res.data else []
    except Exception:
        visits = []

    total_collected = sum([float(v.get('consultation_fee') or 0) for v in visits if v.get('payment_status') == 'Paid'])
    total_pending = sum([float(v.get('consultation_fee') or 0) for v in visits if v.get('payment_status') == 'Pending'])
    total_billed = total_collected + total_pending

    rows = ""
    if visits:
        for idx, v in enumerate(visits, 1):
            p_info = v.get('patients', {})
            p_name = p_info.get('name', 'Unknown')
            p_phone = p_info.get('phone', 'N/A')
            p_id = p_info.get('patient_id', '#')
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

    <!-- Financial Summary Cards -->
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

    <!-- Transaction Ledger Table -->
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
                supabase.table('appointments').update({"status": new_status}).eq('id', appt_id).execute()
            except Exception as e:
                error = f"Error updating status: {str(e)}"

    p_res = supabase.table('patients').select('id, name, phone').order('name').execute()
    patients = p_res.data if p_res.data else []

    a_res = supabase.table('appointments').select('*, patients(name, phone, id)').eq('appointment_date', selected_date).order('created_at').execute()
    appointments = a_res.data if a_res.data else []

    patient_options = "".join([f'<option value="{p["id"]}">{p["name"]} ({p["phone"]})</option>' for p in patients])

    rows = ""
    if appointments:
        for idx, a in enumerate(appointments, 1):
            p_info = a.get('patients', {})
            p_name = p_info.get('name', 'Unknown')
            p_id = p_info.get('id', '#')
            status = a.get('status', 'Waiting')
            
            badge_color = "bg-warning text-dark"
            if status == "In Consultation": badge_color = "bg-info text-dark"
            elif status == "Completed": badge_color = "bg-success"
            elif status == "Cancelled": badge_color = "bg-danger"

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
                            <option value="Waiting" {'selected' if status=='Waiting' else ''}>Waiting</option>
                            <option value="In Consultation" {'selected' if status=='In Consultation' else ''}>In Consultation</option>
                            <option value="Completed" {'selected' if status=='Completed' else ''}>Completed</option>
                            <option value="Cancelled" {'selected' if status=='Cancelled' else ''}>Cancelled</option>
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
    error = None
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        age = request.form.get('age')
        gender = request.form.get('gender')
        
        try:
            response = supabase.table('patients').insert({
                "name": name,
                "phone": phone,
                "age": int(age) if age else None,
                "gender": gender
            }).execute()
            
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
                        <label class="form-label">Age</label>
                        <input type="number" name="age" class="form-control">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Gender</label>
                        <select name="gender" class="form-select">
                            <option value="Male">Male</option>
                            <option value="Female">Female</option>
                            <option value="Other">Other</option>
                        </select>
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
    query = request.args.get('q', '')
    patients = []
    if query:
        res = supabase.table('patients').select('*').or_(f"name.ilike.%{query}%,phone.ilike.%{query}%").execute()
        patients = res.data
    else:
        res = supabase.table('patients').select('*').order('created_at', desc=True).limit(10).execute()
        patients = res.data

    rows = ""
    if patients:
        for p in patients:
            rows += f"""
            <tr>
                <td>{p['name']}</td>
                <td>{p['phone']}</td>
                <td>{p.get('age', '')}</td>
                <td>{p.get('gender', '')}</td>
                <td><a href="/patient/{p['id']}" class="btn btn-sm btn-outline-primary">View Profile</a></td>
            </tr>
            """
    else:
        rows = '<tr><td colspan="5" class="text-center py-4 text-muted">No patients found.</td></tr>'

    body = f"""
    <div class="row justify-content-center">
        <div class="col-md-10">
            <h3 class="mb-4">Patient Directory & Search</h3>
            <form method="GET" class="input-group mb-4">
                <input type="text" name="q" value="{query}" class="form-control" placeholder="Search by name or phone number...">
                <button class="btn btn-primary" type="submit">Search</button>
            </form>
            <div class="card shadow-sm">
                <div class="card-body p-0">
                    <table class="table table-hover mb-0">
                        <thead class="table-light">
                            <tr>
                                <th>Name</th>
                                <th>Phone</th>
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

@app.route('/patient/<int:patient_id>')
@login_required
def patient_profile(patient_id):
    p_res = supabase.table('patients').select('*').eq('id', patient_id).execute()
    if not p_res.data:
        return "Patient not found", 404
    patient = p_res.data[0]

    v_res = supabase.table('visits').select('*, prescriptions(*)').eq('patient_id', patient_id).order('created_at', desc=True).execute()
    visits = v_res.data

    visit_cards = ""
    if visits:
        for v in visits:
            visit_date = v.get('visit_date', v.get('created_at', ''))[:10]
            fee = v.get('consultation_fee', 0)
            pay_status = v.get('payment_status', 'Paid')
            pay_badge = "bg-success" if pay_status == "Paid" else "bg-warning text-dark"

            rx_section = ""
            if v.get('prescriptions'):
                rx = v['prescriptions'][0]
                rx_url = rx['prescription_url']
                doc_type = rx.get('document_type', 'Prescription')
                
                if rx_url.lower().endswith('.pdf'):
                    preview_element = f'<a href="{rx_url}" target="_blank" class="btn btn-sm btn-outline-secondary">📄 Open PDF Document</a>'
                else:
                    preview_element = f'''
                    <a href="{rx_url}" target="_blank">
                        <img src="{rx_url}" alt="{doc_type}" class="img-thumbnail" style="max-height: 150px; object-fit: contain;">
                    </a>
                    '''

                rx_section = f'''
                <div class="mt-3">
                    <span class="badge bg-secondary mb-2">{doc_type}</span>
                    <div>{preview_element}</div>
                    <div class="mt-1">
                        <a href="{rx_url}" target="_blank" class="text-decoration-none small">🔍 View Full File</a>
                    </div>
                </div>
                '''
            
            visit_cards += f"""
            <div class="card shadow-sm mb-3">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-center">
                        <h6 class="text-primary fw-bold mb-0">Visit Date: {visit_date}</h6>
                        <div>
                            <span class="badge bg-dark me-1">Fee: ₹{fee}</span>
                            <span class="badge {pay_badge} me-2">{pay_status}</span>
                            <span class="badge bg-info text-dark">{v.get('diagnosis_tags', '')}</span>
                        </div>
                    </div>
                    <p class="mt-2 mb-2"><strong>Notes:</strong> {v.get('notes', 'No notes recorded.')}</p>
                    {rx_section}
                </div>
            </div>
            """
    else:
        visit_cards = '<div class="alert alert-info text-center">No consultation history recorded yet.</div>'

    body = f"""
    <div class="row">
        <div class="col-md-4">
            <div class="card shadow-sm p-4 mb-4">
                <h4 class="text-primary">{patient['name']}</h4>
                <p class="mb-1"><strong>Phone:</strong> {patient['phone']}</p>
                <p class="mb-1"><strong>Age:</strong> {patient.get('age', '')}</p>
                <p class="mb-3"><strong>Gender:</strong> {patient.get('gender', '')}</p>
                <a href="/visit/new/{patient['id']}" class="btn btn-success w-100 mb-2">🩺 Log New Visit, Scan & Fee</a>
                <a href="/patient/{patient['id']}/print" target="_blank" class="btn btn-outline-secondary w-100">🖨️ Print / Save PDF Summary</a>
            </div>
        </div>
        <div class="col-md-8">
            <h4 class="mb-3">Consultation History & Billing</h4>
            {visit_cards}
        </div>
    </div>
    """
    return render_page(body)

@app.route('/patient/<int:patient_id>/print')
@login_required
def print_patient_summary(patient_id):
    p_res = supabase.table('patients').select('*').eq('id', patient_id).execute()
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
            if v.get('prescriptions'):
                rx = v['prescriptions'][0]
                rx_url = rx['prescription_url']
                doc_type = rx.get('document_type', 'Prescription')
                if not rx_url.lower().endswith('.pdf'):
                    rx_html = f'<div style="margin-top: 10px;"><p><strong>[{doc_type}]</strong></p><img src="{rx_url}" style="max-width: 300px; border: 1px solid #ccc; padding: 5px;" alt="Scan"></div>'
                else:
                    rx_html = f'<div style="margin-top: 10px;"><p><strong>[{doc_type}]</strong> - <a href="{rx_url}" target="_blank">View PDF Document</a></p></div>'

            visit_rows += f"""
            <div style="border-bottom: 1px solid #ddd; padding-bottom: 15px; margin-bottom: 15px;">
                <p><strong>Date:</strong> {visit_date} | <strong>Diagnosis:</strong> {v.get('diagnosis_tags', 'N/A')} | <strong>Fee:</strong> ₹{fee} ({pay_status})</p>
                <p><strong>Notes:</strong> {v.get('notes', 'No notes.')}</p>
                {rx_html}
            </div>
            """
    else:
        visit_rows = "<p>No visit history recorded.</p>"

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
                    <h2>🏥 ClinicDesk - Patient Medical & Billing Summary</h2>
                    <p class="text-muted mb-0">Generated via ClinicDesk SaaS</p>
                </div>
                <button onclick="window.print()" class="btn btn-primary no-print">🖨️ Print / Save PDF</button>
            </div>
            
            <div class="card p-3 mb-4 bg-light border-0">
                <h4 class="text-primary">{patient['name']}</h4>
                <div class="row">
                    <div class="col-md-4"><strong>Phone:</strong> {patient['phone']}</div>
                    <div class="col-md-4"><strong>Age:</strong> {patient.get('age', 'N/A')}</div>
                    <div class="col-md-4"><strong>Gender:</strong> {patient.get('gender', 'N/A')}</div>
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
    if request.method == 'POST':
        diagnosis = request.form.get('diagnosis')
        notes = request.form.get('notes')
        document_type = request.form.get('document_type', 'Prescription')
        fee = request.form.get('consultation_fee', 0)
        payment_status = request.form.get('payment_status', 'Paid')
        file = request.files.get('prescription_file')
        use_ai_ocr = request.form.get('use_ai_ocr')

        file_bytes = None
        mime_type = None
        if file and file.filename != '':
            file_bytes = file.read()
            mime_type = file.content_type or 'image/jpeg'

        if use_ai_ocr and file_bytes:
            ai_diag, ai_notes = extract_medical_file_with_ai(file_bytes, mime_type)
            if not diagnosis or diagnosis.strip() == "":
                diagnosis = ai_diag
            if not notes or notes.strip() == "":
                notes = ai_notes
            else:
                notes = f"{notes}\n\n--- AI OCR Extracted Report ---\n{ai_notes}"

        v_res = supabase.table('visits').insert({
            "patient_id": patient_id,
            "diagnosis_tags": diagnosis,
            "notes": notes,
            "consultation_fee": float(fee) if fee else 0,
            "payment_status": payment_status
        }).execute()

        if v_res.data:
            visit_id = v_res.data[0]['id']

            if file and file_bytes:
                filename = secure_filename(file.filename)
                file_path = f"visit_{visit_id}_{filename}"

                supabase.storage.from_('prescriptions').upload(file_path, file_bytes, {"content-type": mime_type})
                public_url = supabase.storage.from_('prescriptions').get_public_url(file_path)

                supabase.table('prescriptions').insert({
                    "visit_id": visit_id,
                    "prescription_url": public_url,
                    "document_type": document_type
                }).execute()

        return redirect(url_for('patient_profile', patient_id=patient_id))

    p_res = supabase.table('patients').select('*').eq('id', patient_id).execute()
    patient = p_res.data[0] if p_res.data else None
    patient_name = patient['name'] if patient else 'Patient'

    body = f"""
    <div class="row justify-content-center">
        <div class="col-md-7">
            <div class="card shadow-sm p-4">
                <h3 class="mb-3 text-primary">Log Visit, Scan & AI OCR for {patient_name}</h3>
                <form method="POST" enctype="multipart/form-data">
                    <div class="mb-3">
                        <label class="form-label">Upload Scan Image or PDF Report</label>
                        <input type="file" name="prescription_file" id="prescription_file" class="form-control" accept="image/*,.pdf">
                        <div class="form-check mt-2">
                            <input class="form-check-input" type="checkbox" name="use_ai_ocr" id="use_ai_ocr" value="1" checked>
                            <label class="form-check-label fw-semibold text-success" for="use_ai_ocr">
                                🤖 Automatically Extract Diagnosis & Notes using Gemini AI Vision
                            </label>
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Diagnosis / Symptoms (Optional if AI OCR is checked)</label>
                        <input type="text" name="diagnosis" class="form-control" placeholder="e.g. Fever, Cough or let AI fill this">
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
                    <div class="mb-3">
                        <label class="form-label">Document Type</label>
                        <select name="document_type" class="form-select">
                            <option value="Prescription">Prescription</option>
                            <option value="X-Ray">X-Ray / Bone Scan</option>
                            <option value="Ultrasound">Ultrasound / Echo</option>
                            <option value="MRI">MRI / CT Scan</option>
                            <option value="Lab Report">Blood / Lab Report</option>
                        </select>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Save Consultation & Process AI OCR</button>
                </form>
            </div>
        </div>
    </div>
    """
    return render_page(body)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
