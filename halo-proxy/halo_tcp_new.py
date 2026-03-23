import sys
import socketserver
import json
import requests
import time
import urllib.request
import urllib.parse

HA_URL = "http://localhost:8123"
REFRESH_TOKEN = "2418d97efa5d8b1dd8678cccf613d9b3838bb380"

_access_token = None
_token_expiry = 0

def get_access_token():
    global _access_token, _token_expiry
    if _access_token and time.time() < _token_expiry - 60:
        return _access_token
    try:
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": REFRESH_TOKEN}).encode()
        resp = urllib.request.urlopen(urllib.request.Request(
            f"{HA_URL}/auth/token", data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        ))
        result = json.loads(resp.read())
        _access_token = result["access_token"]
        _token_expiry = time.time() + result.get("expires_in", 1800)
        print(f"Token refreshed", flush=True, file=sys.stderr)
        return _access_token
    except Exception as e:
        print(f"Token refresh error: {e}", flush=True, file=sys.stderr)
        return None

MAPPING = {
    "temp":     ("input_number.halo_temp",        -10, 60,    0),
    "humidity": ("input_number.halo_humidity",      0, 100,   0),
    "co2":      ("input_number.halo_co2",           0, 5000,  0),
    "aqi":      ("input_number.halo_aqi",           0, 500,   0),
    "tvoc":     ("input_number.halo_tvoc",          0, 10000, 0),
    "pm25":     ("input_number.halo_pm25",          0, 1000,  0),
    "noise":    ("input_number.halo_noise",         0, 120,   0),
    "motion":   ("input_number.halo_motion",        0, 100,   0),
    "pm1":      ("input_number.halo_pm1",           0, 1000,  0),
    "pm10":     ("input_number.halo_pm10",          0, 1000,  0),
    "co":       ("input_number.halo_co",            0, 100,   0),
    "no2":      ("input_number.halo_no2",           0, 1000,  0),
    "nh3":      ("input_number.halo_nh3",           0, 100,   0),
    "pressure": ("input_number.halo_pressure",    900, 1100,  1013),
    "light":    ("input_number.halo_light",         0, 10000, 0),
    "hi":       ("input_number.halo_health_index",  0, 5,     0),
    "ppc":      ("input_number.halo_occupancy",     0, 50,    0),
    "vape":     ("input_number.halo_vape",        -100, 100,  0),
}

EVENT_ICONS = {
    "Motion": "🚶", "Vape": "💨", "THC": "🌿", "Smoking": "🚬",
    "Gunshot": "🔫", "Aggression": "⚠️", "CO2cal": "💨", "CO": "☠️",
    "Panic_Button": "🚨", "Help": "🆘", "Occupancy": "👥",
    "AQI": "🌫️", "Masking": "🎭",
}

def ha_post(path, payload):
    token = get_access_token()
    if not token:
        return
    try:
        r = requests.post(
            f"{HA_URL}{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload, timeout=5
        )
        print(f"HA {path} -> {r.status_code}", flush=True, file=sys.stderr)
    except Exception as e:
        print(f"HA error: {e}", flush=True, file=sys.stderr)

def handle_heartbeat(j):
    for key, (entity, mn, mx, default) in MAPPING.items():
        try:
            val = j.get(key)
            if val is None or str(val).startswith("?"):
                continue
            val = max(mn, min(mx, float(val)))
            ha_post("/api/services/input_number/set_value", {"entity_id": entity, "value": val})
        except (ValueError, TypeError):
            pass

    pb = str(j.get("pb", "0"))
    panic_active = False
    if not pb.startswith("?"):
        try:
            panic_active = int(float(pb)) > 0
        except (ValueError, TypeError):
            pass

    if not panic_active:
        allsensors = j.get("allsensors", "")
        if allsensors and not allsensors.startswith("?"):
            for part in allsensors.split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    if k.strip().lower() == "panic":
                        try:
                            panic_active = int(float(v.strip())) > 0
                        except (ValueError, TypeError):
                            pass
                        break

    if panic_active:
        ha_post("/api/services/input_boolean/turn_on", {"entity_id": "input_boolean.halo_panic"})
        ha_post("/api/services/meshcore/send_channel_message", {
            "channel_idx": 1,
            "message": f"🚨 PANIC BUTTON — Halo — {j.get(name, Halo)}"
        })

def handle_event(j):
    event = j.get("event", "Unbekannt")
    value = j.get("value", "?")
    threshold = j.get("threshold", "?")
    icon = EVENT_ICONS.get(event, "⚡")
    temp = co2 = aqi = "?"
    allsensors = j.get("allsensors", "")
    if allsensors and not allsensors.startswith("?"):
        try:
            for part in allsensors.split(","):
                if ":" in part:
                    k, v = part.strip().split(":", 1)
                    if k.strip() == "C": temp = v.strip()
                    if k.strip() == "CO2cal": co2 = v.strip()
                    if k.strip() == "AQI": aqi = v.strip()
        except Exception:
            pass
    msg = f"{icon} {event}: {value} (Schwelle: {threshold}) | 🌡{temp}°C CO2:{co2} AQI:{aqi} [{j.get(\"time\", \"?\")}]"
    print(f"EVENT: {msg}", flush=True)
    ha_post("/api/services/meshcore/send_channel_message", {"channel_idx": 1, "message": msg})
    if event == "Panic_Button":
        ha_post("/api/services/input_boolean/turn_on", {"entity_id": "input_boolean.halo_panic"})

class HaloTCPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data = b""
        while True:
            chunk = self.request.recv(4096)
            if not chunk:
                break
            data += chunk
        msg = data.decode("utf-8", errors="replace").strip()
        print(f"TCP from {self.client_address[0]}: {msg[:100]}", flush=True)
        try:
            j = json.loads(msg)
        except Exception as e:
            print(f"JSON error: {e}", flush=True)
            return
        if j.get("type") == "event":
            handle_event(j)
        else:
            handle_heartbeat(j)

if __name__ == "__main__":
    server = socketserver.TCPServer(("0.0.0.0", 9999), HaloTCPHandler)
    server.allow_reuse_address = True
    print("Halo TCP Listener on port 9999", flush=True)
    server.serve_forever()
