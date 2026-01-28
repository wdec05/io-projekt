from flask import Flask, render_template, request, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
import os
import qrcode
from datetime import datetime, timedelta
from uuid import uuid4
from deepface import DeepFace
import pandas as pd
from io import BytesIO
from flask_mail import Mail,Message
from dotenv import load_dotenv

app = Flask(__name__)
load_dotenv()
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///fabryka.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = 'System Fabryka'


mail = Mail(app)
QR_FOLDER = os.path.join('static','qr_codes')
TEMP_FOLDER = os.path.join('static', 'temp')
os.makedirs(QR_FOLDER, exist_ok=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)
SECURITY_FOLDER = os.path.join('static', 'security_captures')
os.makedirs(SECURITY_FOLDER, exist_ok=True)

db = SQLAlchemy(app)

# ===== MODELE =====

class Pracownik(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    qr_code_content = db.Column(db.String(100), unique=True, nullable=True)
    qr_filename = db.Column(db.String(100), nullable=True)
    face_encoding = db.Column(db.PickleType, nullable=True)
    qr_expiry_date = db.Column(db.DateTime, nullable=True)
    email = db.Column(db.String(120), nullable=True)

    # Relacja do logów
    logs = db.relationship('VerificationLog', backref='pracownik', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Pracownik {self.name}>'


class VerificationLog(db.Model):
    """Model do logowania prób weryfikacji"""
    id = db.Column(db.Integer, primary_key=True)
    pracownik_id = db.Column(db.Integer, db.ForeignKey('pracownik.id'), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.now, nullable=False)
    event_type = db.Column(db.String(50), nullable=False)      
    qr_code_used = db.Column(db.String(100), nullable=True)
    similarity_score = db.Column(db.Float, nullable=True)
    success = db.Column(db.Boolean, nullable=False)
    notes = db.Column(db.String(200), nullable=True)
    capture_filename = db.Column(db.String(100), nullable=True)
    def __repr__(self):
        return f'<Log {self.timestamp} - {self.event_type}>'


# ===== FUNKCJE POMOCNICZE =====

def generate_qr_code(content, filename):
    """Generuje kod QR i zapisuje jako plik PNG"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(content)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    save_path = os.path.join(QR_FOLDER, filename)
    img.save(save_path)
    return filename


def log_verification(pracownik_id, event_type, success, qr_code=None, similarity_score=None, notes=None):
    """Zapisuje log weryfikacji do bazy danych"""
    log = VerificationLog(
        pracownik_id=pracownik_id,
        event_type=event_type,
        success=success,
        qr_code_used=qr_code,
        similarity_score=similarity_score,
        notes=notes
    )
    db.session.add(log)
    db.session.commit()
    return log


# ===== ROUTES - PANEL ADMINISTRATORA =====
@app.route('/send_qr_email/<int:employee_id>')
def send_qr_email(employee_id):
    employee = Pracownik.query.get_or_404(employee_id)
    
    if not employee.email or not employee.qr_filename:
        print("Brak maila lub kodu QR")
        return redirect(url_for('admin_dashboard'))

    try:
        msg = Message(f"Twój kod dostępu - {employee.name}",
                      recipients=[employee.email])
        msg.body = f"Witaj {employee.name},\n\nW załączniku znajduje się Twój kod QR ważny do {employee.qr_expiry_date}."
        
        qr_path = os.path.join(QR_FOLDER, employee.qr_filename)
        
        with app.open_resource(qr_path) as fp:
            msg.attach(employee.qr_filename, "image/png", fp.read())
            
        mail.send(msg)
        print(f"Wysłano email do {employee.email}")
    except Exception as e:
        print(f"Błąd wysyłania emaila: {e}")

    return redirect(url_for('admin_dashboard'))
@app.route('/')
def admin_dashboard():
    """Panel administratora - lista wszystkich pracowników"""
    wszyscy_pracownicy = Pracownik.query.all()
    
    # Statystyki
    total_logs = VerificationLog.query.count()
    successful_entries = VerificationLog.query.filter_by(event_type='FACE_SUCCESS', success=True).count()
    failed_entries = VerificationLog.query.filter_by(success=False).count()
    
    return render_template('dashboard.html', 
                         pracownicy=wszyscy_pracownicy, 
                         now=datetime.now(),
                         total_logs=total_logs,
                         successful_entries=successful_entries,
                         failed_entries=failed_entries)


@app.route('/logs')
def view_logs():
    """Strona z historią weryfikacji"""
    # Filtry
    pracownik_id = request.args.get('pracownik_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    event_type = request.args.get('event_type')
    
    # Buduj query
    query = VerificationLog.query
    
    if pracownik_id:
        query = query.filter_by(pracownik_id=pracownik_id)
    
    if date_from:
        date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
        query = query.filter(VerificationLog.timestamp >= date_from_obj)
    
    if date_to:
        date_to_obj = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(VerificationLog.timestamp < date_to_obj)
    
    if event_type:
        query = query.filter_by(event_type=event_type)
    
    # Sortuj od najnowszych
    logs = query.order_by(VerificationLog.timestamp.desc()).limit(500).all()
    
    # Wszyscy pracownicy dla filtra
    wszyscy_pracownicy = Pracownik.query.all()
    
    return render_template('logs.html', 
                         logs=logs, 
                         pracownicy=wszyscy_pracownicy,
                         filters={
                             'pracownik_id': pracownik_id,
                             'date_from': date_from,
                             'date_to': date_to,
                             'event_type': event_type
                         })


@app.route('/download_report')
def download_report():
    """Pobiera raport w formacie Excel"""
    # Filtry (te same co w view_logs)
    pracownik_id = request.args.get('pracownik_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    event_type = request.args.get('event_type')
    
    # Buduj query
    query = VerificationLog.query
    
    if pracownik_id:
        query = query.filter_by(pracownik_id=pracownik_id)
    
    if date_from:
        date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
        query = query.filter(VerificationLog.timestamp >= date_from_obj)
    
    if date_to:
        date_to_obj = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(VerificationLog.timestamp < date_to_obj)
    
    if event_type:
        query = query.filter_by(event_type=event_type)
    
    logs = query.order_by(VerificationLog.timestamp.desc()).all()
    
    # Przygotuj dane do DataFrame
    data = []
    for log in logs:
        data.append({
            'Data i czas': log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'Pracownik': log.pracownik.name if log.pracownik else 'NIEZNANY',
            'Typ zdarzenia': log.event_type,
            'Sukces': 'TAK' if log.success else 'NIE',
            'Podobieństwo': f'{log.similarity_score:.2%}' if log.similarity_score else '-',
            'Notatki': log.notes or '-'
        })
    
    df = pd.DataFrame(data)
    
    # Utwórz plik Excel w pamięci
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Raporty weryfikacji')
        
        # Dodaj arkusz ze statystykami
        stats_data = {
            'Metryka': [
                'Wszystkie zdarzenia',
                'Udane wejścia',
                'Nieudane próby',
                '% skuteczności'
            ],
            'Wartość': [
                len(logs),
                len([l for l in logs if l.event_type == 'FACE_SUCCESS']),
                len([l for l in logs if not l.success]),
                f'{(len([l for l in logs if l.success]) / len(logs) * 100):.1f}%' if logs else '0%'
            ]
        }
        stats_df = pd.DataFrame(stats_data)
        stats_df.to_excel(writer, index=False, sheet_name='Statystyki')
    
    output.seek(0)
    
    filename = f'raport_weryfikacji_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


@app.route('/add', methods=['POST'])
def add_employee():
    """Dodaje nowego pracownika do bazy"""
    new_name = request.form.get('name')  
    new_email = request.form.get('email') 
    new_employee = Pracownik(name=new_name,email=new_email)
    db.session.add(new_employee)
    db.session.commit()
    print(f"✓ Dodano pracownika: {new_name}")
    return redirect(url_for('admin_dashboard'))


@app.route('/generate_qr/<int:employee_id>')
def generate_qr(employee_id):
    """Generuje kod QR dla pracownika"""
    employee = Pracownik.query.get_or_404(employee_id)
    expiry_date = datetime.now() + timedelta(days=30)

    unique_content = str(uuid4())
    filename = f'qr_{employee_id}_{unique_content}.png'
    save_path = generate_qr_code(unique_content, filename)
    
    employee.qr_code_content = unique_content
    employee.qr_filename = filename
    employee.qr_expiry_date = expiry_date
    db.session.commit()

    print(f"✓ Wygenerowano QR dla: {employee.name} (ważny do {expiry_date.strftime('%Y-%m-%d')})")
    return redirect(url_for('admin_dashboard'))


@app.route('/upload_photo/<int:employee_id>', methods=['POST'])
def upload_photo(employee_id):
    """Przesyła zdjęcie twarzy pracownika i generuje encoding"""
    employee = Pracownik.query.get_or_404(employee_id)
    
    if 'photo' not in request.files:
        print("✗ Brak pliku w żądaniu")
        return redirect(url_for('admin_dashboard'))
    
    file = request.files['photo']
    if file.filename == '':
        print("✗ Nie wybrano pliku")
        return redirect(url_for('admin_dashboard'))
    
    try:
        temp_path = os.path.join(TEMP_FOLDER, f'temp_{employee_id}.jpg')
        file.save(temp_path)
        
        print(f"Przetwarzanie zdjęcia dla {employee.name}...")
        
        embedding_objs = DeepFace.represent(
            img_path=temp_path,
            model_name='Facenet512',
            enforce_detection=True,
            detector_backend='retinaface'
        )
        
        if embedding_objs and len(embedding_objs) > 0:
            employee.face_encoding = embedding_objs[0]['embedding']
            db.session.commit()
            print(f"✓ Zapisano encoding dla pracownika: {employee.name}")
        else:
            print("✗ Nie wykryto twarzy na zdjęciu")
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
    except ValueError as e:
        print(f"✗ Nie wykryto twarzy na zdjęciu: {e}")
    except Exception as e:
        print(f"✗ Błąd podczas przetwarzania zdjęcia: {e}")
    
    return redirect(url_for('admin_dashboard'))


@app.route('/delete/<int:employee_id>')
def delete_employee(employee_id):
    """Usuwa pracownika z bazy danych"""
    employee = Pracownik.query.get_or_404(employee_id)
    
    if employee.qr_filename:
        qr_path = os.path.join(QR_FOLDER, employee.qr_filename)
        if os.path.exists(qr_path):
            os.remove(qr_path)
    
    name = employee.name
    db.session.delete(employee)
    db.session.commit()
    
    print(f"✗ Usunięto pracownika: {name}")
    return redirect(url_for('admin_dashboard'))


@app.route('/regenerate_qr/<int:employee_id>')
def regenerate_qr(employee_id):
    """Regeneruje kod QR (np. po wygaśnięciu)"""
    employee = Pracownik.query.get_or_404(employee_id)
    
    if employee.qr_filename:
        old_qr_path = os.path.join(QR_FOLDER, employee.qr_filename)
        if os.path.exists(old_qr_path):
            os.remove(old_qr_path)
    
    expiry_date = datetime.now() + timedelta(days=30)
    unique_content = str(uuid4())
    filename = f'qr_{employee_id}_{unique_content}.png'
    generate_qr_code(unique_content, filename)
    
    employee.qr_code_content = unique_content
    employee.qr_filename = filename
    employee.qr_expiry_date = expiry_date
    db.session.commit()
    
    print(f"✓ Regenerowano QR dla: {employee.name}")
    return redirect(url_for('admin_dashboard'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("=" * 50)
        print("PANEL ADMINISTRATORA - System weryfikacji pracowników")
        print("=" * 50)
        print(f"Liczba pracowników w bazie: {Pracownik.query.count()}")
        print(f"Liczba logów weryfikacji: {VerificationLog.query.count()}")
        print("Uruchamiam serwer na http://127.0.0.1:5000")
        print("=" * 50)
    app.run(debug=True)