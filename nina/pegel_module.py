# ============================================================
# RUHR-PEGEL MODUL — ergänzt nina_monitor.py
# Schwellen basierend auf historischen WSV-Daten
# ============================================================

PEGEL_STATIONS = {
    "Hattingen": {
        "station": "Hattingen",
        "einheit": "cm",
        # Schwellen in cm (relativ zum Pegelnullpunkt 60.38m ü.NHN)
        # Normal: ~80-200cm | Mittel: ~213cm aktuell
        # Schleusenstraße flutet ab 620cm
        # HHW Juli 2021: ~699cm
        "schwellen": [
            (300, "⚡ AUFMERKSAMKEIT"),
            (400, "🟡 HOCHWASSER Stufe 1"),
            (520, "🟠 HOCHWASSER Stufe 2"),
            (620, "🔴 HOCHWASSER Stufe 3 — Schleusenstraße überflutet"),
        ]
    },
    "Muelheim": {
        "station": "SCHLOSSBRÜCKE MÜLHEIM",
        "einheit": "m+NN",
        # Station misst in m+NN (Pegelnullpunkt 28.25m)
        # Normalstand: ~28.5-29.5m (ca. 25-135cm rel.)
        # Umrechnung: Wert - 28.251 = relativer Stand in m
        # Schwellen als absoluter m+NN Wert
        "schwellen": [
            (31.5, "⚡ AUFMERKSAMKEIT"),
            (32.5, "🟡 HOCHWASSER Stufe 1"),
            (33.5, "🟠 HOCHWASSER Stufe 2"),
            (35.0, "🔴 HOCHWASSER Stufe 3"),
        ]
    },
}

PEGEL_STATE_FILE = "/opt/nina/pegel_state.json"
PEGEL_DAILY_FILE = "/opt/nina/pegel_last_daily.json"

import requests, json, os
from datetime import datetime, date

def fetch_pegel(station_key):
    """Fetch current measurement from pegelonline WSV API"""
    cfg = PEGEL_STATIONS[station_key]
    station_name = cfg["station"]
    try:
        import urllib.parse
        name_enc = urllib.parse.quote(station_name)
        url = f"https://www.pegelonline.wsv.de/webservices/rest-api/v2/stations/{name_enc}/W/currentmeasurement.json"
        r = requests.get(url, timeout=10)
        if r.ok:
            data = r.json()
            return float(data["value"]), data["timestamp"]
    except Exception as e:
        print(f"Pegel fetch error {station_key}: {e}")
    return None, None

def load_pegel_state():
    try:
        if os.path.exists(PEGEL_STATE_FILE):
            with open(PEGEL_STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {"alarmed": {}}  # {"STATION_LEVEL": last_alarm_ts}

def save_pegel_state(state):
    with open(PEGEL_STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_daily_state():
    try:
        if os.path.exists(PEGEL_DAILY_FILE):
            with open(PEGEL_DAILY_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {"last_date": ""}

def save_daily_state(state):
    with open(PEGEL_DAILY_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def format_pegel_value(val, einheit):
    if einheit == "cm":
        return f"{val:.0f} cm"
    else:
        rel_cm = (val - 28.251) * 100
        return f"{rel_cm:.0f} cm (abs: {val:.2f}m ü.NHN)"

def check_pegel_alarms(send_channel_fn, send_room_fn):
    """Check water levels and send alarms if thresholds exceeded. Call every hour during HW, daily otherwise."""
    state = load_pegel_state()
    now = datetime.now()
    now_str = now.strftime("%H:%M")
    any_hw = False

    for key, cfg in PEGEL_STATIONS.items():
        val, ts = fetch_pegel(key)
        if val is None:
            continue

        einheit = cfg["einheit"]
        schwellen = cfg["schwellen"]
        
        # Find highest exceeded threshold
        active_stufe = None
        for threshold, label in sorted(schwellen, reverse=True):
            if val >= threshold:
                active_stufe = (threshold, label)
                break

        alarm_key = f"{key}_{active_stufe[0] if active_stufe else 'none'}"
        
        if active_stufe:
            any_hw = True
            threshold, label = active_stufe
            # Send alarm if not already alarmed for this level (cooldown: 1h)
            last_alarm = state["alarmed"].get(alarm_key, "")
            should_send = True
            if last_alarm:
                try:
                    last_dt = datetime.fromisoformat(last_alarm)
                    cooldown = 21600 if "AUFMERKSAMKEIT" in label else 3600
                    if (now - last_dt).total_seconds() < cooldown:
                        should_send = False
                except Exception:
                    pass
            
            if should_send:
                val_str = format_pegel_value(val, einheit)
                msg = f"💧 RUHR-PEGEL {key.upper()} | {label} | {val_str} | {now_str} Uhr"
                send_channel_fn(msg)
                send_room_fn(msg)
                state["alarmed"][alarm_key] = now.isoformat()
                print(f"Pegel-Alarm gesendet: {key} {label} @ {val_str}")
        else:
            # Clear alarm state if back to normal
            for threshold, _ in schwellen:
                k = f"{key}_{threshold}"
                if k in state["alarmed"]:
                    del state["alarmed"][k]

    save_pegel_state(state)
    return any_hw

def check_pegel_daily(send_channel_fn, send_room_fn):
    """Send daily morning report at 7:00. Returns True if sent."""
    daily_state = load_daily_state()
    today = date.today().isoformat()
    hour = datetime.now().hour
    
    if daily_state.get("last_date") == today:
        return False  # already sent today
    if hour < 7 or hour > 9:
        return False  # only send between 7-9h
    
    parts = []
    for key in ["Hattingen", "Muelheim"]:
        val, ts = fetch_pegel(key)
        if val is not None:
            cfg = PEGEL_STATIONS[key]
            if cfg["einheit"] == "cm":
                parts.append(f"{key}: {val:.0f}cm")
            else:
                rel_cm = (val - 28.251) * 100
                parts.append(f"Mülheim: {rel_cm:.0f}cm")
    
    if parts:
        ts_str = datetime.now().strftime("%d.%m. %H:%M")
        msg = f"📊 Ruhr-Pegel {ts_str} | " + " | ".join(parts)
        send_channel_fn(msg)
        print(f"Pegel-Tagesbericht gesendet: {msg}")
        daily_state["last_date"] = today
        save_daily_state(daily_state)
        return True
    return False

def run_pegel_check(send_channel_fn, send_room_fn, test_mode=False):
    """Main entry point. Call from nina_monitor main loop."""
    if test_mode:
        # Force send current values regardless of time/state
        parts = []
        for key in ["Hattingen", "Muelheim"]:
            val, ts = fetch_pegel(key)
            if val is not None:
                cfg = PEGEL_STATIONS[key]
                if cfg["einheit"] == "cm":
                    parts.append(f"{key}: {val:.0f}cm")
                else:
                    rel_cm = (val - 28.251) * 100
                    parts.append(f"Mülheim: {rel_cm:.0f}cm")
        ts_str = datetime.now().strftime("%d.%m. %H:%M")
        msg = f"📊 Ruhr-Pegel TEST {ts_str} | " + " | ".join(parts)
        send_channel_fn(msg)
        send_room_fn(msg)
        print(f"✅ Pegel-Test gesendet: {msg}")
        return
    
    any_hw = check_pegel_alarms(send_channel_fn, send_room_fn)
    check_pegel_daily(send_channel_fn, send_room_fn)
