from flask import Flask, render_template, request, redirect, url_for
from supabase import create_client, Client
import os

app = Flask(__name__)

# TODO: Replace with your actual Supabase project credentials
SUPABASE_URL = "YOUR_SUPABASE_URL"
SUPABASE_KEY = "YOUR_SUPABASE_KEY"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route('/')
def index():
    return "<h1>Welcome to ClinicDesk SaaS</h1><p>Cloud backend is live and running!</p>"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
