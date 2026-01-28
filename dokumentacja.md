# Dokumentacja Techniczna

System Kontroli Dostępu

---

## 1. Przegląd Technologii

System został zaimplementowany w języku **Python 3.12** i składa się z dwóch głównych modułów:

- **Serwer Zarządzający (Backend)**  \
  Oparty na mikro-frameworku **Flask**. Odpowiada za logikę programu, obsługę bazy danych (ORM) oraz interfejs administratora (HTML/Jinja2).

- **Terminal Weryfikacyjny**  \
  Aplikacja kliencka wykorzystująca **OpenCV** do przetwarzania obrazu oraz **DeepFace** do biometrii. Działa w pętli nieskończonej, analizując strumień wideo w czasie rzeczywistym.

### Główne biblioteki

- **Flask-SQLAlchemy** – obsługa bazy danych SQLite
- **DeepFace** – implementacja modelu *FaceNet512 (Google)* do embeddingu twarzy
- **OpenCV (cv2)** – obsługa kamery, rysowanie GUI na klatkach wideo
- **Pandas / OpenPyXL** – generowanie raportów Excel

---


## 2. Kluczowe Funkcje i Algorytmy

### A. Backend (app.py)

#### 1. upload_photo(employee_id)
- Przyjmuje plik graficzny, zapisuje go tymczasowo, a następnie przekazuje do `DeepFace.represent`. Funkcja ekstrahuje wektor cech (*embedding*) i zapisuje go w bazie danych jako obiekt Python (Pickle). Oryginalne zdjęcie jest usuwane w celu oszczędności miejsca.

#### 2. download_report()
- Pobiera logi z bazy danych, konwertuje je do `Pandas DataFrame`, a następnie generuje plik Excel w pamięci RAM (`BytesIO`).

### B. Terminal (terminal.py)

#### 1. scan_qr(frame)

- Wykorzystuje detektor kodów QR z OpenCV. Po wykryciu kodu łączy się z bazą danych i sprawdza ważność przypisanego pracownikowi QR. Stosuje `db.session.expunge(employee)` oraz `make_transient()`, aby przenieść obiekt pracownika do pamięci RAM i natychmiast zamknąć połączenie z bazą. Dzięki temu terminal nie blokuje bazy danych podczas długotrwałego oczekiwania na twarz.

#### 2. verify_face_async(frame)
- Główny wątek odpowiada za płynne wyświetlanie obrazu z kamery, podczas gdy wątek poboczny wykonuje obliczenia.
- Obliczanie podobieństwa cosinusowego wektorów cech:

  $$
  Similarity = \frac{A \cdot B}{||A|| \cdot ||B||}
  $$

  Jeśli wynik **> 0.80** (próg dobrany eksperymentalnie), weryfikacja zostaje uznana za poprawną.

#### 3. Stany w pętli run()

Aplikacja działa jako maszyna stanów:

- `WAITING_QR` – skanowanie klatek w poszukiwaniu kodu QR
- `WAITING_FACE` – oczekiwanie na twarz, odliczanie prób (maks. 3)
- `VERIFIED / DENIED` – wyświetlenie wyniku oraz blokada skanowania na czas *cooldown*

---

## 3. Bezpieczeństwo

- **Rejestracja incydentów**  \
  W przypadku trzykrotnego błędu weryfikacji system wykonuje zrzut klatki wideo (*snapshot*) i zapisuje go w katalogu `security_captures`.  \
  Plik jest linkowany w logach bazy danych jako zdarzenie krytyczne.

