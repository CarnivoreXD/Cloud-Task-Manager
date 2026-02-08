"""
Cloud Task Manager - Flask Application
AWS Cognito Authentication + Role-Based Access Control
Deployed on AWS EKS (Kubernetes) with Docker
"""

import os
import json
import hmac
import hashlib
import base64
import requests as http_requests
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify
)
from flask_sqlalchemy import SQLAlchemy
from jose import jwt, JWTError
from jose.utils import base64url_decode

# ============================================================
# App Configuration
# ============================================================
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-in-prod')

# Database - SQLite locally, RDS Postgres in production
db_url = os.environ.get('DATABASE_URL', 'sqlite:///tasks.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# AWS Cognito Configuration
COGNITO_REGION = os.environ.get('COGNITO_REGION', 'us-west-2')
COGNITO_USER_POOL_ID = os.environ.get('COGNITO_USER_POOL_ID', '')
COGNITO_CLIENT_ID = os.environ.get('COGNITO_CLIENT_ID', '')
COGNITO_CLIENT_SECRET = os.environ.get('COGNITO_CLIENT_SECRET', '')
COGNITO_DOMAIN = os.environ.get('COGNITO_DOMAIN', '')
APP_URL = os.environ.get('APP_URL', 'http://localhost:5000')

COGNITO_ISSUER = f'https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}'
COGNITO_JWKS_URL = f'{COGNITO_ISSUER}/.well-known/jwks.json'
COGNITO_TOKEN_URL = f'https://{COGNITO_DOMAIN}/oauth2/token'
COGNITO_AUTH_URL = f'https://{COGNITO_DOMAIN}/oauth2/authorize'
COGNITO_LOGOUT_URL = f'https://{COGNITO_DOMAIN}/logout'

# Cache JWKS keys
_jwks_cache = None


def get_jwks():
    """Fetch and cache Cognito JWKS keys for JWT validation."""
    global _jwks_cache
    if _jwks_cache is None:
        resp = http_requests.get(COGNITO_JWKS_URL, timeout=5)
        _jwks_cache = resp.json()['keys']
    return _jwks_cache


# ============================================================
# Database Models
# ============================================================
class Task(db.Model):
    """Task model - core entity."""
    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    status = db.Column(db.String(20), default='pending')  # pending, in_progress, completed
    priority = db.Column(db.String(10), default='medium')  # low, medium, high
    user_id = db.Column(db.String(100), nullable=False)     # Cognito sub
    user_email = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'status': self.status,
            'priority': self.priority,
            'user_email': self.user_email,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }


class AuditLog(db.Model):
    """Audit log for RBAC demonstration."""
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(200))
    action = db.Column(db.String(50))
    resource_type = db.Column(db.String(50))
    resource_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


# ============================================================
# Helper Functions
# ============================================================
def compute_secret_hash(username):
    """Compute SECRET_HASH for Cognito API calls."""
    if not COGNITO_CLIENT_SECRET:
        return None
    message = username + COGNITO_CLIENT_ID
    dig = hmac.new(
        COGNITO_CLIENT_SECRET.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).digest()
    return base64.b64encode(dig).decode()


def log_action(user_email, action, resource_type, resource_id=None, details=''):
    """Write an entry to the audit log."""
    entry = AuditLog(
        user_email=user_email,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    )
    db.session.add(entry)
    db.session.commit()


def verify_token(token):
    """Verify a Cognito JWT id_token and return claims."""
    try:
        headers = jwt.get_unverified_headers(token)
        kid = headers['kid']

        keys = get_jwks()
        key = next((k for k in keys if k['kid'] == kid), None)
        if not key:
            return None

        claims = jwt.decode(
            token,
            key,
            algorithms=['RS256'],
            audience=COGNITO_CLIENT_ID,
            issuer=COGNITO_ISSUER,
        )
        return claims
    except JWTError:
        return None


def get_user_groups(access_token):
    """Get the user's Cognito groups via the access token claims."""
    try:
        claims = jwt.get_unverified_claims(access_token)
        return claims.get('cognito:groups', [])
    except Exception:
        return []


# ============================================================
# Auth Decorators
# ============================================================
def login_required(f):
    """Require authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Require admin role (Cognito 'admin' group)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            flash('Please log in.', 'warning')
            return redirect(url_for('login'))
        if not session.get('is_admin'):
            flash('Admin access required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ============================================================
# Auth Routes
# ============================================================
@app.route('/login')
def login():
    """Redirect to Cognito Hosted UI."""
    if COGNITO_DOMAIN:
        callback = f'{APP_URL}/callback'
        auth_url = (
            f'{COGNITO_AUTH_URL}'
            f'?client_id={COGNITO_CLIENT_ID}'
            f'&response_type=code'
            f'&scope=openid+email+profile'
            f'&redirect_uri={callback}'
        )
        return redirect(auth_url)
    # Local dev fallback
    return render_template('login_local.html')


@app.route('/login/local', methods=['POST'])
def login_local():
    """Local dev login (no Cognito)."""
    email = request.form.get('email', 'dev@local.test')
    role = request.form.get('role', 'user')
    session['user'] = {
        'sub': f'local-{email}',
        'email': email,
    }
    session['is_admin'] = (role == 'admin')
    flash(f'Logged in as {email} ({role})', 'success')
    return redirect(url_for('dashboard'))


@app.route('/callback')
def callback():
    """Handle Cognito OAuth2 callback."""
    code = request.args.get('code')
    if not code:
        flash('Authentication failed.', 'error')
        return redirect(url_for('index'))

    # Exchange code for tokens
    callback_uri = f'{APP_URL}/callback'
    data = {
        'grant_type': 'authorization_code',
        'client_id': COGNITO_CLIENT_ID,
        'code': code,
        'redirect_uri': callback_uri,
    }

    # Build auth header
    if COGNITO_CLIENT_SECRET:
        auth_string = f'{COGNITO_CLIENT_ID}:{COGNITO_CLIENT_SECRET}'
        auth_b64 = base64.b64encode(auth_string.encode()).decode()
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {auth_b64}',
        }
    else:
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    resp = http_requests.post(COGNITO_TOKEN_URL, data=data, headers=headers, timeout=10)
    if resp.status_code != 200:
        flash('Token exchange failed.', 'error')
        return redirect(url_for('index'))

    tokens = resp.json()
    id_token = tokens.get('id_token')
    access_token = tokens.get('access_token')

    # Verify and decode the id token
    claims = verify_token(id_token)
    if not claims:
        flash('Invalid token.', 'error')
        return redirect(url_for('index'))

    # Store user info in session
    session['user'] = {
        'sub': claims['sub'],
        'email': claims.get('email', 'unknown'),
    }

    # Check admin group membership (RBAC)
    groups = get_user_groups(access_token)
    session['is_admin'] = 'admin' in groups

    log_action(claims.get('email'), 'login', 'session', details=f'Groups: {groups}')
    flash(f'Welcome, {claims.get("email")}!', 'success')
    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    """Log out and redirect to Cognito logout."""
    email = session.get('user', {}).get('email', 'unknown')
    log_action(email, 'logout', 'session')
    session.clear()

    if COGNITO_DOMAIN:
        logout_url = (
            f'{COGNITO_LOGOUT_URL}'
            f'?client_id={COGNITO_CLIENT_ID}'
            f'&logout_uri={APP_URL}'
        )
        return redirect(logout_url)
    return redirect(url_for('index'))


# ============================================================
# Page Routes
# ============================================================
@app.route('/')
def index():
    """Landing page."""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/dashboard')
@login_required
def dashboard():
    """User dashboard - shows own tasks."""
    user_id = session['user']['sub']
    tasks = Task.query.filter_by(user_id=user_id).order_by(Task.created_at.desc()).all()
    stats = {
        'total': len(tasks),
        'pending': sum(1 for t in tasks if t.status == 'pending'),
        'in_progress': sum(1 for t in tasks if t.status == 'in_progress'),
        'completed': sum(1 for t in tasks if t.status == 'completed'),
    }
    return render_template('dashboard.html', tasks=tasks, stats=stats)


@app.route('/task/new', methods=['GET', 'POST'])
@login_required
def create_task():
    """Create a new task."""
    if request.method == 'POST':
        task = Task(
            title=request.form['title'],
            description=request.form.get('description', ''),
            priority=request.form.get('priority', 'medium'),
            user_id=session['user']['sub'],
            user_email=session['user']['email'],
        )
        db.session.add(task)
        db.session.commit()
        log_action(session['user']['email'], 'create', 'task', task.id, task.title)
        flash('Task created!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('task_form.html', task=None)


@app.route('/task/<int:task_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_task(task_id):
    """Edit an existing task."""
    task = Task.query.get_or_404(task_id)
    if task.user_id != session['user']['sub'] and not session.get('is_admin'):
        flash('Permission denied.', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        task.title = request.form['title']
        task.description = request.form.get('description', '')
        task.status = request.form.get('status', task.status)
        task.priority = request.form.get('priority', task.priority)
        db.session.commit()
        log_action(session['user']['email'], 'update', 'task', task.id, task.title)
        flash('Task updated!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('task_form.html', task=task)


@app.route('/task/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    """Delete a task."""
    task = Task.query.get_or_404(task_id)
    if task.user_id != session['user']['sub'] and not session.get('is_admin'):
        flash('Permission denied.', 'error')
        return redirect(url_for('dashboard'))

    log_action(session['user']['email'], 'delete', 'task', task.id, task.title)
    db.session.delete(task)
    db.session.commit()
    flash('Task deleted.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/task/<int:task_id>/status', methods=['POST'])
@login_required
def update_status(task_id):
    """AJAX status update."""
    task = Task.query.get_or_404(task_id)
    if task.user_id != session['user']['sub'] and not session.get('is_admin'):
        return jsonify({'error': 'Forbidden'}), 403

    data = request.get_json()
    task.status = data.get('status', task.status)
    db.session.commit()
    log_action(session['user']['email'], 'status_change', 'task', task.id, task.status)
    return jsonify({'success': True, 'task': task.to_dict()})


# ============================================================
# Admin Routes (RBAC)
# ============================================================
@app.route('/admin')
@admin_required
def admin_dashboard():
    """Admin panel - all tasks, all users, audit log."""
    tasks = Task.query.order_by(Task.created_at.desc()).all()
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(50).all()
    user_stats = (
        db.session.query(Task.user_email, db.func.count(Task.id))
        .group_by(Task.user_email).all()
    )
    return render_template('admin.html', tasks=tasks, logs=logs, user_stats=user_stats)


@app.route('/admin/task/<int:task_id>/delete', methods=['POST'])
@admin_required
def admin_delete_task(task_id):
    """Admin can delete any task."""
    task = Task.query.get_or_404(task_id)
    log_action(session['user']['email'], 'admin_delete', 'task', task.id, task.title)
    db.session.delete(task)
    db.session.commit()
    flash('Task deleted by admin.', 'success')
    return redirect(url_for('admin_dashboard'))


# ============================================================
# API + Health Endpoints
# ============================================================
@app.route('/api/tasks')
@login_required
def api_tasks():
    """REST API endpoint for tasks."""
    uid = session['user']['sub']
    if session.get('is_admin') and request.args.get('all') == 'true':
        tasks = Task.query.all()
    else:
        tasks = Task.query.filter_by(user_id=uid).all()
    return jsonify([t.to_dict() for t in tasks])


@app.route('/health')
def health():
    """Health check for load balancer / Kubernetes."""
    return jsonify({'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()})


@app.route('/api/metrics')
def metrics():
    """Basic metrics endpoint (Prometheus-compatible)."""
    total = Task.query.count()
    pending = Task.query.filter_by(status='pending').count()
    in_progress = Task.query.filter_by(status='in_progress').count()
    completed = Task.query.filter_by(status='completed').count()
    return (
        f'# HELP tasks_total Total tasks\n'
        f'# TYPE tasks_total gauge\n'
        f'tasks_total {total}\n'
        f'tasks_pending {pending}\n'
        f'tasks_in_progress {in_progress}\n'
        f'tasks_completed {completed}\n'
    ), 200, {'Content-Type': 'text/plain'}


# ============================================================
# Initialise
# ============================================================
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
