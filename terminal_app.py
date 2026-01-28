import cv2
import numpy as np
from deepface import DeepFace
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import make_transient
from datetime import datetime
import time
import threading
import os

# Konfiguracja bazy danych
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///fabryka.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
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
    logs = db.relationship('VerificationLog', backref='pracownik', lazy=True)
    def __repr__(self):
        return f'<Pracownik {self.name}>'

class VerificationLog(db.Model):
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

def log_verification(pracownik_id, event_type, success, qr_code=None, similarity_score=None, notes=None,image_filename=None):
    """Zapisuje log w osobnej, krótkiej transakcji"""
    with app.app_context():
        try:
            log = VerificationLog(
                pracownik_id=pracownik_id,
                event_type=event_type,
                success=success,
                qr_code_used=qr_code,
                similarity_score=similarity_score,
                notes=notes,
                capture_filename=image_filename
            )
            db.session.add(log)
            db.session.commit()
            print(f" LOG ZAPISANY: {event_type}")
        except Exception as e:
            print(f" BŁĄD LOGOWANIA: {e}")

# Kolory
COLOR_GREEN = (0, 255, 0)
COLOR_RED = (0, 0, 255)
COLOR_BLUE = (255, 0, 0)
COLOR_YELLOW = (0, 255, 255)
COLOR_ORANGE = (0, 165, 255) # BGR
COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)

class TerminalApp:
    def __init__(self):
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        
        self.qr_detector = cv2.QRCodeDetector()

        self.state = "WAITING_QR"
        self.current_employee = None
        self.message = "Pokaz kod QR"
        self.message_color = COLOR_WHITE
        self.last_qr_time = 0
        self.last_verification_time = 0
        self.cooldown = 3
        
        # Zmienne dla weryfikacji twarzy
        self.face_verification_running = False
        self.face_verification_result = None
        self.face_verification_similarity = 0.0
        
        # Zmienne do obsługi prób
        self.max_face_attempts = 3
        self.current_face_attempt = 0
        self.next_attempt_time = 0 
        
    def draw_ui(self, frame):
        height, width = frame.shape[:2]
        
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (width, 180), COLOR_BLACK, -1)
        cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)
        
        
        cv2.putText(frame, self.message, (50, 70), 
                   cv2.FONT_HERSHEY_DUPLEX, 1.5, self.message_color, 3)
        
        if self.current_employee:
            cv2.putText(frame, f"Pracownik: {self.current_employee.name}", 
                       (50, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.0, COLOR_WHITE, 2)
            
            # Licznik prób
            if self.state == "WAITING_FACE":
                attempts_info = f"Proba: {self.current_face_attempt + 1}/{self.max_face_attempts}"
                cv2.putText(frame, attempts_info, (width - 300, 130), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1.0, COLOR_ORANGE, 2)
        
        # Pasek statusu
        instruction_y = height - 50
        status_text = f"Stan: {self.state}"
        
        if self.face_verification_running:
            status_text += " | PRZETWARZANIE..."
            cv2.putText(frame, ">>> NIE RUSZAJ SIE <<<", (width//2 - 200, height//2), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1.5, COLOR_YELLOW, 3)
            
        cv2.putText(frame, status_text, (50, instruction_y), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)
        
        # Ramki sukcesu/błędu
        if self.state == "VERIFIED":
            cv2.rectangle(frame, (20, 20), (width-20, height-20), COLOR_GREEN, 15)
        elif self.state == "DENIED":
            cv2.rectangle(frame, (20, 20), (width-20, height-20), COLOR_RED, 15)
        
        return frame
    
    def scan_qr(self, frame):
        """Skanuje QR i zwraca obiekt pracownika ODŁĄCZONY od sesji DB"""
        current_time = time.time()
        
        if current_time - self.last_qr_time < self.cooldown:
            return None
        
        try:  
          qr_data, bbox, _ = self.qr_detector.detectAndDecode(frame)
        except cv2.error as e:
          print(f"Błąd OpenCV przy skanowaniu QR: {e}")
          return None
        except Exception as e:
          print(f"Inny błąd skanera: {e}")
          return None
        if qr_data:
            
            with app.app_context():
                employee = Pracownik.query.filter_by(qr_code_content=qr_data).first()
                
                if not employee:
                    self.message = "NIEZNANY KOD QR"
                    self.message_color = COLOR_RED
                    self.last_qr_time = current_time
                    log_verification(None, 'QR_INVALID', False, qr_code=qr_data)
                    return None
                
                # Walidacja daty
                if employee.qr_expiry_date and employee.qr_expiry_date < datetime.now():
                    self.message = "KOD QR WYGASL"
                    self.message_color = COLOR_RED
                    self.last_qr_time = current_time
                    log_verification(employee.id, 'QR_EXPIRED', False, qr_code=qr_data)
                    return None
                
                # Walidacja twarzy
                if not employee.face_encoding:
                    self.message = "BRAK DANYCH TWARZY"
                    self.message_color = COLOR_RED
                    self.last_qr_time = current_time
                    log_verification(employee.id, 'NO_FACE_DATA', False, qr_code=qr_data)
                    return None
                
                # Odłączamy obiekt od bazy
                # Dzięki temu możemy zamknąć sesję, a obiekt nadal działa w pamięci
                db.session.expunge(employee)
                make_transient(employee)
                
                # Zapisujemy log sukcesu QR (osobna transakcja wewnątrz log_verification)
                log_verification(employee.id, 'QR_SUCCESS', True, qr_code=qr_data)
                
                self.last_qr_time = current_time
                return employee
                
        return None
    
    def verify_face_async(self, frame):
        frame_to_verify = frame.copy()
        
        stored_embedding = self.current_employee.face_encoding
        
        def _verify():
            try:
                temp_path = f'temp_verify_{int(time.time())}.jpg'
                cv2.imwrite(temp_path, frame_to_verify)
                
                embedding_objs = DeepFace.represent(
                    img_path=temp_path,
                    model_name='Facenet512',
                    enforce_detection=True,
                    detector_backend='retinaface'
                )
                
                new_embedding = embedding_objs[0]['embedding']
                
                similarity = np.dot(new_embedding, stored_embedding) / (
                    np.linalg.norm(new_embedding) * np.linalg.norm(stored_embedding)
                )
                
                threshold = 0.65 
                is_match = similarity > threshold
                
                self.face_verification_similarity = similarity
                self.face_verification_result = is_match 
                
                print(f"DEBUG: Similarity: {similarity:.4f}, Match: {is_match}")
                
            except ValueError:
                print("DEBUG: Nie wykryto twarzy na zdjęciu")
                self.face_verification_result = "NO_FACE"
                self.face_verification_similarity = 0.0
                
            except Exception as e:
                print(f"Błąd krytyczny weryfikacji: {e}")
                self.face_verification_result = "NO_FACE"
                
            finally:
                self.face_verification_running = False
        
        self.face_verification_running = True
        self.face_verification_result = None
        thread = threading.Thread(target=_verify)
        thread.daemon = True
        thread.start()
    
    def run(self):
        print("=== SYSTEM URUCHOMIONY ===")
        save_folder = os.path.join('static', 'security_captures')
        os.makedirs(save_folder, exist_ok=True)
        while True:
            ret, frame = self.cap.read()
            if not ret: break
            frame = cv2.flip(frame, 1)
            current_time = time.time()
            
            # === STAN 1: CZEKANIE NA QR ===
            if self.state == "WAITING_QR":
                employee = self.scan_qr(frame)
                
                if employee:
                    self.current_employee = employee
                    self.state = "WAITING_FACE"
                    self.message = f"Witaj {employee.name}!"
                    self.message_color = COLOR_BLUE
                    
                    self.current_face_attempt = 0
                    self.next_attempt_time = current_time + 1.5 
            
            # === STAN 2: CZEKANIE NA TWARZ ===
            elif self.state == "WAITING_FACE":
                if current_time > self.next_attempt_time:
                    if not self.face_verification_running and self.face_verification_result is None:
                        self.verify_face_async(frame)
                    
                    elif self.face_verification_result is not None:
                        result = self.face_verification_result
                        sim = self.face_verification_similarity
                        
                        # 1. BRAK TWARZY
                        if result == "NO_FACE":
                            self.message = "Nie widze twarzy! Ustaw sie."
                            self.message_color = COLOR_YELLOW
                            self.next_attempt_time = current_time + 2.0 
                            self.face_verification_result = None
                            
                        # 2. SUKCES
                        elif result == True: 
                            self.state = "VERIFIED"
                            self.message = f"WERYFIKACJA OK ({sim:.1%})"
                            self.message_color = COLOR_GREEN
                            self.last_verification_time = current_time
                            self.face_verification_result = None
                            
                            # Logowanie
                            log_verification(self.current_employee.id, 'FACE_SUCCESS', True, similarity_score=sim)
                            
                        # 3. PORAŻKA
                        elif result == False:
                            self.current_face_attempt += 1
                            attempts_left = self.max_face_attempts - self.current_face_attempt
                            
                            log_verification(self.current_employee.id, 'FACE_ATTEMPT_FAIL', False, similarity_score=sim, notes=f'Proba {self.current_face_attempt}')
                            
                            if self.current_face_attempt >= self.max_face_attempts:
                                self.state = "DENIED"
                                self.message = "DOSTEP ODRZUCONY"
                                self.message_color = COLOR_RED
                                self.last_verification_time = current_time

                                filename = f"alert_{int(time.time())}_{self.current_employee.id}.jpg"
                                filepath = os.path.join(save_folder, filename)
                                cv2.imwrite(filepath, frame)
                                print(f"!!! Zapisano zdjęcie naruszenia: {filename}")

                                log_verification(self.current_employee.id, 'FACE_FAILED_FINAL', False, similarity_score=sim,image_filename=filename)
                                self.face_verification_result = None
                            else:
                                self.message = f"Blad! Pozostalo prob: {attempts_left}"
                                self.message_color = COLOR_ORANGE
                                self.next_attempt_time = current_time + 2.5
                                self.face_verification_result = None

            # === STAN 3: WYNIK KOŃCOWY ===
            elif self.state in ["VERIFIED", "DENIED"]:
                if current_time - self.last_verification_time > self.cooldown:
                    self.state = "WAITING_QR"
                    self.message = "Pokaz kod QR"
                    self.message_color = COLOR_WHITE
                    self.current_employee = None
            
            frame = self.draw_ui(frame)
            cv2.imshow('Terminal', frame)
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        
        self.cap.release()
        cv2.destroyAllWindows()

if __name__ == '__main__':
    TerminalApp().run()