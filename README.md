# 🏭 System Weryfikacji Pracowników

System rejestracji wejść i wyjść pracowników wykorzystujący **kody QR** i **rozpoznawanie twarzy**.

---

## 🚀 Instalacja

### 1. Zainstaluj zależności:
```bash
pip install -r requirements.txt
```

### 2. Uruchom aplikację:
```bash
# Panel administratora
python app.py

# Terminal weryfikacyjny (w osobnym terminalu)
python terminal.py
```

---

## 📊 Struktura projektu

```
projekt/
├── app.py                    # Panel administratora (Flask)
├── terminal.py               # Terminal weryfikacyjny (OpenCV)
├── requirements.txt          # Zależności
├── fabryka.db               # Baza danych SQLite
├── templates/
│   ├── dashboard.html       # Panel główny
│   └── logs.html           # Historia weryfikacji
└── static/
    ├── qr_codes/           # Wygenerowane kody QR
    └── temp/               # Tymczasowe zdjęcia
```

---

## 🎯 Jak używać?

### **Panel Administratora** (`http://127.0.0.1:5000`)

1. **Dodaj pracownika** - wpisz imię i nazwisko
2. **Wygeneruj kod QR** - kliknij "Generuj QR"
3. **Dodaj zdjęcie twarzy** - wybierz plik i prześlij
4. **Sprawdź historię** - kliknij "Historia weryfikacji"
5. **Pobierz raport** - kliknij "Pobierz raport Excel"

### **Terminal Weryfikacyjny**

1. **Uruchom:** `python terminal.py`
2. **Pokaż kod QR** do kamery
3. **Pokaż twarz** do kamery
4. System automatycznie weryfikuje i loguje wynik

---

## 📈 Typy logowanych zdarzeń

| Typ zdarzenia | Opis |
|--------------|------|
| `QR_SUCCESS` | Kod QR poprawnie zeskanowany |
| `QR_INVALID` | Nieznany kod QR |
| `QR_EXPIRED` | Kod QR wygasł |
| `NO_FACE_DATA` | Pracownik nie ma zarejestrowanej twarzy |
| `FACE_SUCCESS` | Twarz zweryfikowana |
| `FACE_FAILED` | Twarz nie pasuje |

---

## 📥 Raporty Excel

Pobierany raport zawiera:

### **Arkusz 1: Raporty weryfikacji**
- Data i czas
- Pracownik
- Typ zdarzenia
- Sukces (TAK/NIE)
- Podobieństwo (%)
- Notatki

### **Arkusz 2: Statystyki**
- Wszystkie zdarzenia
- Udane wejścia
- Nieudane próby
- % skuteczności

---

## 🔧 Konfiguracja

### Próg weryfikacji twarzy
W pliku `terminal.py` zmień wartość:
```python
threshold = 0.85  # Domyślnie 85% podobieństwa
```

### Ważność kodu QR
W pliku `app.py` zmień wartość:
```python
expiry_date = datetime.now() + timedelta(days=30)  # Domyślnie 30 dni
```

### Cooldown między weryfikacjami
W pliku `terminal.py`:
```python
self.cooldown = 3  # sekundy
```

---

## 🎨 Filtry w historii weryfikacji

- **Pracownik** - wybierz konkretną osobę
- **Typ zdarzenia** - QR/twarz/błędy
- **Data od/do** - zakres czasowy
- **Pobierz raport** - eksportuj wyfiltrowane dane

---

## 🛡️ Bezpieczeństwo

- Kody QR są unikalne (UUID)
- Kody QR wygasają po 30 dniach
- Encoding twarzy wykorzystuje Facenet512 (512-wymiarowy wektor)
- Wszystkie próby dostępu są logowane
- Baza danych lokalna (SQLite)
---

### Błąd "No face detected"
- Upewnij się, że zdjęcie jest wyraźne
- Twarz powinna być dobrze oświetlona
- Spróbuj innego zdjęcia

### Niska skuteczność rozpoznawania
- Zwiększ oświetlenie przy kamerze
- Zmniejsz próg weryfikacji (np. 0.80)
- Zaktualizuj zdjęcie pracownika

