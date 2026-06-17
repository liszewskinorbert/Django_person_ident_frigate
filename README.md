# Monitoring Detektor

System monitoringu oparty na Frigate NVR z interfejsem webowym Django. Rejestruje zdarzenia detekcji obiektów (osoby, pojazdy, zwierzęta) z kamer IP, przechowuje snapshoty i klipy wideo oraz udostępnia panel zarządzania.

## Architektura

```
Kamera IP (RTSP)
      │
      ▼
  Frigate NVR (Docker)
      │
      ├─► MQTT Broker / Eclipse Mosquitto (Docker)
      │         │
      │         ▼
      │   mqtt_listener (Django)
      │         │
      │         ▼
      │     SQLite DB
      │
      └─► Frigate API :5000
                │
                ▼
          Django Web :8000
```

## Wymagania

- Ubuntu 22.04+
- Docker + Docker Compose
- Python 3.12
- Frigate NVR 0.17+
- Eclipse Mosquitto 2.x

## Struktura projektu

```
monitoring-detektor/
├── django/
│   ├── manage.py
│   ├── db.sqlite3
│   ├── media/
│   │   ├── snapshots/          # zdjęcia ze zdarzeń (przetworzone OpenCV)
│   │   └── thumbnails/         # miniatury do listy zdarzeń
│   ├── monitoring/             # główna aplikacja Django
│   │   ├── models.py           # model CameraEvent
│   │   ├── views.py            # widoki: lista, szczegóły, statystyki, kamery
│   │   ├── urls.py
│   │   ├── opencv_utils.py     # pobieranie i adnotowanie snapshotów
│   │   ├── management/
│   │   │   └── commands/
│   │   │       ├── mqtt_listener.py    # nasłuch zdarzeń z Frigate
│   │   │       ├── snapshot_fetcher.py # demon pobierający snapshoty co 5s
│   │   │       ├── fetch_snapshots.py  # jednorazowe pobranie brakujących
│   │   │       └── fix_clip_urls.py    # naprawa starych URL klipów
│   │   └── templates/monitoring/
│   │       ├── base.html
│   │       ├── login.html
│   │       ├── event_list.html
│   │       ├── event_detail.html
│   │       ├── statistics.html
│   │       └── camera_preview.html
│   └── monitoring_site/
│       └── settings.py
├── monitoring-mqtt.service      # systemd: nasłuch MQTT
├── monitoring-web.service       # systemd: serwer Django
└── monitoring-snapshots.service # systemd: demon snapshotów
```

## Instalacja na Ubuntu

### 1. Klonowanie projektu

```bash
git clone <repo> /opt/monitoring
cd /opt/monitoring/django
```

### 2. Środowisko Python

```bash
python3 -m venv venv
source venv/bin/activate
pip install django paho-mqtt opencv-python-headless requests
```

### 3. Konfiguracja

Edytuj `monitoring_site/settings.py`:

```python
FRIGATE_BASE_URL = "http://<IP_SERWERA>:5000"
FRIGATE_RECORDINGS_PATH = "/media/frigate/recordings"
MQTT_HOST = "localhost"
MQTT_PORT = 1883
```

### 4. Baza danych

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 5. Usługi systemd

```bash
sudo cp monitoring-mqtt.service /etc/systemd/system/
sudo cp monitoring-web.service /etc/systemd/system/
sudo cp monitoring-snapshots.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable monitoring-mqtt monitoring-web monitoring-snapshots
sudo systemctl start monitoring-mqtt monitoring-web monitoring-snapshots
```

### 6. Docker (Frigate + Mosquitto)

```bash
docker compose up -d
sudo systemctl enable docker
```

## Kolejność startu po restarcie systemu

1. Docker → kontenery `frigate` i `mqtt` (restart: unless-stopped)
2. `monitoring-mqtt.service` — czeka na port 1883 i 5000, następnie startuje nasłuch
3. `monitoring-web.service` — serwer Django na porcie 8000
4. `monitoring-snapshots.service` — demon pobierający snapshoty co 5 sekund

## Interfejs webowy

Dostępny pod: `http://<IP_SERWERA>:8000`

| Strona | URL | Opis |
|--------|-----|------|
| Logowanie | `/login/` | Ekran logowania |
| Kamery | `/events/camera/` | Podgląd ostatniego obrazu z każdej kamery |
| Zdarzenia | `/events/` | Lista zdarzeń z filtrami |
| Szczegóły | `/events/<id>/` | Snapshot, klip wideo, zmiana statusu |
| Statystyki | `/events/statistics/` | Wykresy i podsumowania |
| Admin | `/admin/` | Panel administracyjny Django |

## Komendy zarządzania

```bash
cd /opt/monitoring/django
source venv/bin/activate

# Nasłuch MQTT (uruchamiany przez systemd)
python manage.py mqtt_listener

# Demon snapshotów (uruchamiany przez systemd)
python manage.py snapshot_fetcher

# Jednorazowe pobranie brakujących snapshotów
python manage.py fetch_snapshots
python manage.py fetch_snapshots --limit 50

# Naprawa starych URL klipów w bazie
python manage.py fix_clip_urls
```

## Logi

```bash
sudo journalctl -u monitoring-mqtt.service -f
sudo journalctl -u monitoring-web.service -f
sudo journalctl -u monitoring-snapshots.service -f
```

## Model danych — CameraEvent

| Pole | Typ | Opis |
|------|-----|------|
| `frigate_event_id` | CharField | Unikalny ID zdarzenia z Frigate |
| `camera_name` | CharField | Nazwa kamery |
| `label` | CharField | Typ obiektu: person, car, dog, cat |
| `started_at` | DateTimeField | Czas rozpoczęcia detekcji |
| `ended_at` | DateTimeField | Czas zakończenia detekcji |
| `top_score` | FloatField | Najwyższa pewność detekcji (0-1) |
| `has_snapshot` | BooleanField | Czy dostępny snapshot |
| `has_clip` | BooleanField | Czy dostępny klip wideo |
| `snapshot_url` | CharField | Ścieżka do snapshotu (względna do MEDIA_ROOT) |
| `thumbnail_url` | CharField | Ścieżka do miniatury |
| `clip_url` | CharField | URL klipu w Frigate API |
| `reviewed` | BooleanField | Czy zdarzenie przejrzane |
| `false_alarm` | BooleanField | Czy fałszywy alarm |

## Nagrania wideo

Frigate zapisuje nagrania w strukturze:
```
/media/frigate/recordings/
└── YYYY-MM-DD/
    └── HH/
        └── camera_name/
            └── MM.SS.mp4
```

Django szuka klipów na dysku na podstawie daty i godziny zdarzenia (`started_at`). Klip jest również dostępny przez Frigate API: `http://<IP>:5000/api/events/<id>/clip.mp4`
