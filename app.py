import os
from flask import Flask, redirect, render_template_string, request, url_for
from supabase import Client, create_client
from werkzeug.utils import secure_filename

app = Flask(__name__)

# ClinicDesk Supabase Credentials
SUPABASE_URL = "https://pfmldhpidblncypuagld.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBmbWxkaHBpZGJsbmN5cHVhZ2xkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTQ2NTM2MjEsImV4cCI6MjExMDIyOTYyMX0.SI7i2c5IeGwP3T3qi0GaCEPU-WUeRFP2T4oh0Ioun0c"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Single unified template wrapper
def render_page(body_content, **kwargs):
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
                    <a href="/" class="btn btn-outline-light btn-sm me-2">Home</a>
                    <a href="/search" class="btn btn-outline-light btn-sm me-2">Search Patients</a>
                    <a href="/register" class="btn btn-light btn-sm">Register Patient</a>
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

@app.route('/')
def index():
    body = """
    <div class="row justify-content-center">
        <div class="col-md-8 text-center py-5">
            <h1 class="display-5 fw-bold text-primary">ClinicDesk Management</h1>
            <p class="lead text-muted">Cloud-native patient records and prescription management for independent clinics.</p>
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
            rx_btn = ""
            if v.get('prescriptions'):
                rx_url = v['prescriptions'][0]['prescription_url']
                rx_btn = f'<a href="{rx_url}" target="_blank" class="btn btn-sm btn-outline-dark ms-2">View Prescription Image 📄</a>'
            
            visit_cards += f"""
            <div class="card shadow-sm mb-3 p-3">
                <div class="d-flex justify-content-between">
                    <h5 class="text-secondary">Visit Date: {v['visit_date']}</h5>
                    <span class="badge bg-info text-dark">{v.get('diagnosis_tags', '')}</span>
                </div>
                <p class="mt-2 mb-2"><strong>Notes:</strong> {v.get('notes', '')}</p>
                <div class="mt-2"><strong>Prescription:</strong> {rx_btn}</div>
            </div>
            """
    else:
        visit_cards = '<div class="card shadow-sm p-4 text-center text-muted">No consultation history recorded yet.</div>'

    body = f"""
    <div class="row">
        <div class="col-md-4">
            <div class="card shadow-sm p-4 mb-4">
                <h4 class="text-primary">{patient['name']}</h4>
                <p class="mb-1"><strong>Phone:</strong> {patient['phone']}</p>
                <p class="mb-1"><strong>Age:</strong> {patient.get('age', '')}</p>
                <p class="mb-3"><strong>Gender:</strong> {patient.get('gender', '')}</p>
                <a href="/visit/new/{patient['id']}" class="btn btn-success w-100">🩺 Log New Visit & Rx</a>
            </div>
        </div>
        <div class="col-md-8">
            <h4 class="mb-3">Consultation History</h4>
            {visit_cards}
        </div>
    </div>
    """
    return render_page(body)

@app.route('/visit/new/<int:patient_id>', methods=['GET', 'POST'])
def log_visit(patient_id):
    if request.method == 'POST':
        diagnosis = request.form.get('diagnosis')
        notes = request.form.get('notes')
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

                supabase.storage.from_('PRESCRIPTIONS').upload(file_path, file_bytes, {"content-type": file.content_type})
                public_url = supabase.storage.from_('PRESCRIPTIONS').get_public_url(file_path)

                supabase.table('prescriptions').insert({
                    "visit_id": visit_id,
                    "prescription_url": public_url
                }).execute()

        return redirect(url_for('patient_profile', patient_id=patient_id))

    p_res = supabase.table('patients').select('*').eq('id', patient_id).execute()
    patient = p_res.data[0] if p_res.data else None

    body = f"""
    <div class="row justify-content-center">
        <div class="col-md-6">
            <div class="card shadow-sm p-4">
                <h3 class="mb-3 text-primary">Log Visit for {patient['name']}</h3>
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
                        <label class="form-label">Upload Prescription Image / Scan</label>
                        <input type="file" name="prescription_file" class="form-control" accept="image/*">
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Save Consultation</button>
                </form>
            </div>
        </div>
    </div>
    """
    return render_page(body)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
