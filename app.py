import os
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
            <a href="/" class="btn btn-outline-light btn-sm me-2">Home</a>
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
        except Exception as e:
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
    body = """
    <div class="row justify-content-center">
        <div class="col-md-8 text-center py-5">
            <h1 class="display-5 fw-bold text-primary">ClinicDesk Management</h1>
            <p class="lead text-muted">Cloud-native patient records and medical scan management for independent clinics.</p>
            <hr class="my-4">
            <div class="d-flex justify-content-center gap-3">
                <a href="/register" class="btn btn-primary btn-lg">➕ Register Patient</a>
                <a href="/search" class="btn btn-outline-secondary btn-lg">🔍 Search & View Records</a>
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
                        <span class="badge bg-info text-dark">{v.get('diagnosis_tags', '')}</span>
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
                <a href="/visit/new/{patient['id']}" class="btn btn-success w-100 mb-2">🩺 Log New Visit & Scan</a>
                <a href="/patient/{patient['id']}/print" target="_blank" class="btn btn-outline-secondary w-100">🖨️ Print / Save PDF Summary</a>
            </div>
        </div>
        <div class="col-md-8">
            <h4 class="mb-3">Consultation History</h4>
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
                <p><strong>Date:</strong> {visit_date} | <strong>Diagnosis/Symptoms:</strong> {v.get('diagnosis_tags', 'N/A')}</p>
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
        <title>Patient Medical Summary - {patient['name']}</title>
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
                    <h2>🏥 ClinicDesk - Patient Medical Summary</h2>
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

            <h4 class="mb-3">Visit, Prescription & Scan History</h4>
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
        file = request.files.get('prescription_file')

        v_res = supabase.table('visits').insert({
            "patient_id": patient_id,
            "diagnosis_tags": diagnosis,
            "notes": notes
        }).execute()

        if v_res.data:
            visit_id = v_res.data[0]['id']

            if file and file.filename != '':
                filename = secure_filename(file.filename)
                file_path = f"visit_{visit_id}_{filename}"
                file_bytes = file.read()

                supabase.storage.from_('prescriptions').upload(file_path, file_bytes, {"content-type": file.content_type})
                public_url = supabase.storage.from_('prescriptions').get_public_url(file_path)

                supabase.table('prescriptions').insert({
                    "visit_id": visit_id,
                    "prescription_url": public_url,
                    "document_type": document_type
                }).execute()

        return redirect(url_for('patient_profile', patient_id=patient_id))

    p_res = supabase.table('patients').select('*').eq('id', patient_id).execute()
    patient = p_res.data[0] if p_res.data else None

    body = f"""
    <div class="row justify-content-center">
        <div class="col-md-6">
            <div class="card shadow-sm p-4">
                <h3 class="mb-3 text-primary">Log Visit & Scan for {patient['name']}</h3>
                <form method="POST" enctype="multipart/form-data">
                    <div class="mb-3">
                        <label class="form-label">Diagnosis / Symptoms</label>
                        <input type="text" name="diagnosis" class="form-control" placeholder="e.g. Fever, Cough, Hypertension" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Clinical Notes</label>
                        <textarea name="notes" class="form-control" rows="3" placeholder="Prescription details, dosage, advice..."></textarea>
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
                    <div class="mb-3">
                        <label class="form-label">Upload Scan Image or PDF Report</label>
                        <input type="file" name="prescription_file" class="form-control" accept="image/*,.pdf">
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Save Consultation & File</button>
                </form>
            </div>
        </div>
    </div>
    """
    return render_page(body)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
