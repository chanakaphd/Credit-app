from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here'  # Change to a random string
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Database Models
class CreditFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False)  # Leasing, Loan, Other
    application_number = db.Column(db.String(12), unique=True, nullable=False)  # 12-digit alphanumeric
    marketing_officer_name = db.Column(db.String(100), nullable=False)  # Mandatory field
    status = db.Column(db.String(50), default='Created')  # Created, In Compliance, In Documentation, Checked, Returned, Completed
    current_assignee_role = db.Column(db.String(50), default='compliance')  # compliance, documentation, marketing
    returned_by = db.Column(db.String(50), nullable=True)  # Track who returned the file: compliance or documentation
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    credit_file_id = db.Column(db.Integer, db.ForeignKey('credit_file.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    role = db.Column(db.String(50), nullable=False)  # Role that made the comment
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Create database
with app.app_context():
    db.create_all()

# Routes
@app.route('/')
def index():
    if 'logged_in' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form['password']
        # Single shared password for simplicity (change this in Replit)
        if password == 'branch123':  # Replace with your own password
            session['logged_in'] = True
            flash('Logged in successfully!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid password', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    selected_role = request.form.get('role') if request.method == 'POST' else session.get('selected_role', 'marketing')
    session['selected_role'] = selected_role

    if selected_role == 'marketing':
        files = CreditFile.query.filter_by(current_assignee_role='marketing').all()
        returned_files = CreditFile.query.filter_by(status='Returned', current_assignee_role='marketing').all()
        completed_files = []
    elif selected_role == 'documentation':
        files = CreditFile.query.filter_by(current_assignee_role='documentation').all()
        returned_files = []
        completed_files = CreditFile.query.filter_by(status='Completed').all()
    else:
        files = CreditFile.query.filter_by(current_assignee_role=selected_role).all()
        returned_files = []
        completed_files = []

    return render_template('dashboard.html', files=files, returned_files=returned_files, completed_files=completed_files, role=selected_role)

@app.route('/create_file', methods=['GET', 'POST'])
def create_file():
    if 'logged_in' not in session or session.get('selected_role') != 'marketing':
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        type = request.form['type']
        application_number = request.form['application_number']
        marketing_officer_name = request.form['marketing_officer_name']
        
        # Validate application number (12-digit alphanumeric)
        if not re.match(r'^[A-Za-z0-9]{12}$', application_number):
            flash('Application number must be exactly 12 alphanumeric characters', 'error')
            return render_template('create_file.html')

        # Validate marketing officer name
        if not marketing_officer_name.strip():
            flash('Marketing Officer Name is required', 'error')
            return render_template('create_file.html')

        # Check if application number is unique
        if CreditFile.query.filter_by(application_number=application_number).first():
            flash('Application number already exists', 'error')
            return render_template('create_file.html')

        new_file = CreditFile(
            type=type,
            application_number=application_number,
            marketing_officer_name=marketing_officer_name,
            status='In Compliance',
            current_assignee_role='compliance'
        )
        db.session.add(new_file)
        db.session.commit()
        flash('Credit file created and sent to Compliance', 'success')
        return redirect(url_for('dashboard'))

    return render_template('create_file.html')

@app.route('/view_file/<int:file_id>', methods=['GET', 'POST'])
def view_file(file_id):
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    file = CreditFile.query.get_or_404(file_id)
    comments = Comment.query.filter_by(credit_file_id=file_id).order_by(Comment.created_at.desc()).all()
    role = session.get('selected_role')

    if file.current_assignee_role != role:
        flash('Access denied: File not assigned to your selected role', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        action = request.form['action']
        comment_text = request.form.get('comment')

        if action == 'check' and role == 'documentation':
            file.status = 'Checked'
            db.session.commit()
            flash('File checked. Proceed to complete or return.', 'success')
            return render_template('view_file.html', file=file, comments=comments, role=role)

        if action == 'forward':
            if role == 'compliance':
                file.status = 'In Documentation'
                file.current_assignee_role = 'documentation'
                file.returned_by = None
                flash('File forwarded to Documentation', 'success')
            elif role == 'documentation' and file.status == 'Checked':
                file.status = 'Completed'
                file.current_assignee_role = None
                file.completed_at = datetime.utcnow()
                file.returned_by = None
                flash('File completed', 'success')

        elif action == 'return':
            if not comment_text:
                flash('Remark required to return file', 'error')
                return render_template('view_file.html', file=file, comments=comments, role=role)
            new_comment = Comment(credit_file_id=file_id, text=comment_text, role=role)
            db.session.add(new_comment)
            file.status = 'Returned'
            file.current_assignee_role = 'marketing'
            file.returned_by = role  # Track who returned the file
            flash('File returned to Marketing with remarks', 'success')

        elif action == 'correct' and role == 'marketing':
            type = request.form['type']
            application_number = request.form['application_number']
            marketing_officer_name = request.form['marketing_officer_name']
            
            if not re.match(r'^[A-Za-z0-9]{12}$', application_number):
                flash('Application number must be exactly 12 alphanumeric characters', 'error')
                return render_template('view_file.html', file=file, comments=comments, role=role)
            
            if not marketing_officer_name.strip():
                flash('Marketing Officer Name is required', 'error')
                return render_template('view_file.html', file=file, comments=comments, role=role)
            
            if application_number != file.application_number and CreditFile.query.filter_by(application_number=application_number).first():
                flash('Application number already exists', 'error')
                return render_template('view_file.html', file=file, comments=comments, role=role)

            file.type = type
            file.application_number = application_number
            file.marketing_officer_name = marketing_officer_name
            file.status = 'In ' + file.returned_by.capitalize() if file.returned_by else 'In Compliance'
            file.current_assignee_role = file.returned_by if file.returned_by else 'compliance'
            flash('File corrected and resubmitted to ' + (file.returned_by or 'compliance').capitalize(), 'success')

        db.session.commit()
        return redirect(url_for('dashboard'))

    # Calculate time taken
    time_taken = None
    if file.completed_at:
        time_taken = file.completed_at - file.created_at
        time_taken = str(time_taken).split('.')[0]  # Format as string (days, hours, minutes)

    return render_template('view_file.html', file=file, comments=comments, role=role, time_taken=time_taken)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
