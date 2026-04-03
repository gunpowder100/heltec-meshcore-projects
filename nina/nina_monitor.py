#!/usr/bin/env python3
import requests
import json
import time
import os
import sys
from datetime import datetime

HA_URL        = "http://localhost:8123"
# Token aus zentraler Config laden
def _load_token():
    try:
        with open('/opt/nina/config.env') as f:
            for line in f:
                if line.startswith('HA_TOKEN='):
                    return line.strip().split('=', 1)[1]
    except Exception:
        pass
    return ''
HA_TOKEN      = _load_token()
CHANNEL_IDX   = 2          # NINA-RUHRPOTT
ROOM_PUBKEY   = "f3f4af"   # DE-NW-NINA-NOT Room
STATE_FILE    = "/opt/nina/seen_warnings.json"
NINA_BASE     = "https://warnung.bund.de/api31"
NINA_JSON     = "/config/www/nina_current.json"

REGIONS = {
    "Essen":          "051130000000",
    "Muelheim":       "051170000000",
    "Oberhausen":     "051190000000",
    "Duisburg":       "051120000000",
    "Kreis Mettmann": "051580000000",
    "Velbert":        "051580056000",
}

REGION_ENTITY = {
    "Essen":          "input_text.nina_warn_ess",
    "Muelheim":       "input_text.nina_warn_mue",
    "Oberhausen":     "input_text.nina_warn_obe",
    "Duisburg":       "input_text.nina_warn_dui",
    "Kreis Mettmann": "input_text.nina_warn_met",
    "Velbert":        "input_text.nina_warn_met",
    "Dusseldorf":     "input_text.nina_warn_ddf",
}

SEVERITY = {
    "Minor":    "GERING",
    "Moderate": "MITTEL",
    "Severe":   "HOCH",
    "Extreme":  "EXTREM",
    "Unknown":  "UNBEKANNT",
}

SEVERITY_EMOJI = {
    "Minor":    "🟢",  # Grün für gering
    "Moderate": "🟡",  # Gelb für mittel
    "Severe":   "🟠",  # Orange für hoch
    "Extreme":  "🔴",  # Rot für extrem
    "Unknown":  "⚪",  # Weiß für unbekannt
}

def add_emojis_to_message(headline, severity):
    """Fügt passende Emojis basierend auf Headline-Inhalt und Severity hinzu"""
    # Basis-Emoji basierend auf Severity
    emojis = [SEVERITY_EMOJI.get(severity, "⚪")]
    
    # Headline-basierte Emojis
    headline_lower = headline.lower()
    
    if "rauch" in headline_lower or "rauchgas" in headline_lower:
        emojis.append("💨")
    if "feuer" in headline_lower:
        emojis.append("🔥")
    if "wasser" in headline_lower or "hochwasser" in headline_lower or "überschwemmung" in headline_lower:
        emojis.append("💧")
    if "sturm" in headline_lower or "wind" in headline_lower or "orkan" in headline_lower:
        emojis.append("💨🌀")
    if "unwetter" in headline_lower:
        emojis.append("⛈️")
    if "gewitter" in headline_lower:
        emojis.append("⚡")
    if "chemie" in headline_lower or "gift" in headline_lower:
        emojis.append("☣️")
    if "atom" in headline_lower or "strahlung" in headline_lower:
        emojis.append("☢️")
    if "entwarnung" in headline_lower:
        emojis.append("✅")
    if "test" in headline_lower:
        emojis.append("🧪")
    if "ess" in headline_lower or "essen" in headline_lower:
        emojis.append("🏭")
    if "duisburg" in headline_lower:
        emojis.append("⚓")
    if "mülheim" in headline_lower or "muelheim" in headline_lower:
        emojis.append("🌉")
    if "oberhausen" in headline_lower:
        emojis.append("🎡")
    
    # Generische Emojis für bestimmte Muster
    if any(word in headline_lower for word in ["warnung", "alarm", "gefahr"]):
        if "🔴" not in emojis and "🟠" not in emojis:
            emojis.append("⚠️")
    
    # Emojis zusammenfügen (einmalig, keine Duplikate)
    unique_emojis = []
    for emoji in emojis:
        if emoji not in unique_emojis:
            unique_emojis.append(emoji)
    
    return " ".join(unique_emojis) + " "

HEADERS = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json"
}

TEST_WARNING = {
    "id": "NINA-TEST-001",
    "region": "Essen",
    "severity": "Severe",
    "headline": "🧪 NINA Testwarnung – Bitte ignorieren (Systemtest)",
    "type": "Test",
    "sent": datetime.now().isoformat(),
}


def load_seen():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(STATE_FILE, "w") as f:
        json.dump(list(seen), f)


def fetch_warnings(ars):
    try:
        r = requests.get(f"{NINA_BASE}/dashboard/{ars}.json", timeout=10)
        return r.json() if r.ok else []
    except Exception as e:
        print(f"Fetch error {ars}: {e}")
        return []


def send_channel(msg):
    try:
        r = requests.post(
            f"{HA_URL}/api/services/meshcore/send_channel_message",
            headers=HEADERS,
            json={"channel_idx": CHANNEL_IDX, "message": msg},
            timeout=10
        )
        print(f"Channel [{r.status_code}]: {msg[:80]}")
    except Exception as e:
        print(f"Channel error: {e}")


def send_room(msg):
    try:
        r = requests.post(
            f"{HA_URL}/api/services/meshcore/send_message",
            headers=HEADERS,
            json={"pubkey_prefix": ROOM_PUBKEY, "message": msg},
            timeout=10
        )
        print(f"Room [{r.status_code}]: {msg[:80]}")
    except Exception as e:
        print(f"Room error: {e}")


def update_city_text(region, text):
    entity = REGION_ENTITY.get(region)
    if not entity:
        return
    try:
        requests.post(
            f"{HA_URL}/api/services/input_text/set_value",
            headers=HEADERS,
            json={"entity_id": entity, "value": text[:255]},
            timeout=10
        )
    except Exception as e:
        print(f"City text error {region}: {e}")


def update_ha_sensor(all_warnings):
    count = len(all_warnings)
    try:
        requests.post(
            f"{HA_URL}/api/services/input_text/set_value",
            headers=HEADERS,
            json={"entity_id": "input_text.nina_active_warnings", "value": str(count)},
            timeout=10
        )
        requests.post(
            f"{HA_URL}/api/services/input_datetime/set_datetime",
            headers=HEADERS,
            json={"entity_id": "input_datetime.nina_last_update",
                  "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
            timeout=10
        )
        print(f"HA sensor updated: {count} warnings")
    except Exception as e:
        print(f"HA sensor update error: {e}")


def check(test_mode=False):
    seen = load_seen()
    new_seen = set(seen)
    all_warnings = []

    if test_mode:
        print("=== TEST MODE ===")
        w = TEST_WARNING.copy()
        w["sent"] = datetime.now().isoformat()
        sev_de = SEVERITY.get(w["severity"], w["severity"])
        emojis = add_emojis_to_message(w["headline"], w["severity"])
        msg = emojis + "[NINA/" + w["region"] + "] " + sev_de + ": " + w["headline"][:80]
        send_channel(msg)
        send_room(msg)
        all_warnings = [w]
        with open(NINA_JSON, "w") as f:
            json.dump(all_warnings, f, ensure_ascii=False, indent=2)
        update_ha_sensor(all_warnings)
        print("✅ Test alert sent to Channel " + str(CHANNEL_IDX) + " + Room " + ROOM_PUBKEY)
        return

    # Reset all city texts at start of each check cycle
    for r in list(REGION_ENTITY.keys()):
        update_city_text(r, "Keine Warnung")

    region_headlines = {}  # track best headline per region

    seen_ars = set()
    for region, ars in REGIONS.items():
        if ars in seen_ars:
            continue
        seen_ars.add(ars)
        warnings = fetch_warnings(ars)
        for w in warnings:
            wid = w.get("id", "")
            if not wid:
                continue
            payload = w.get("payload", {}).get("data", {})
            severity = payload.get("severity", "Unknown")
            headline = (payload.get("headline", "") or
                        w.get("i18nTitle", {}).get("de", "Warnung"))
            msgtype = payload.get("msgType", "")
            sent = w.get("sent", "")

            all_warnings.append({
                "id": wid, "region": region,
                "severity": severity, "headline": headline,
                "type": msgtype, "sent": sent,
            })
            # Update city warning text (keep first/most severe)
            if region not in region_headlines:
                sev_de2 = SEVERITY.get(severity, severity)

                ts = datetime.now().strftime("%d.%m. %H:%M")
                region_headlines[region] = "[" + ts + "] " + sev_de2 + ": " + headline[:180]
                update_city_text(region, region_headlines[region])

            if wid not in seen:
                sev_de = SEVERITY.get(severity, severity)
                emojis = add_emojis_to_message(headline, severity)
                msg = emojis + "[NINA/" + region + "] " + sev_de + ": " + headline[:80]
                send_channel(msg)
                send_room(msg)
                new_seen.add(wid)

    with open(NINA_JSON, "w") as f:
        json.dump(all_warnings, f, ensure_ascii=False, indent=2)

    update_ha_sensor(all_warnings)
    save_seen(new_seen)
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{ts} - {len(all_warnings)} Warnungen, {len(new_seen) - len(seen)} neu")


if __name__ == "__main__":
    test_mode = "--test" in sys.argv
    if test_mode:
        check(test_mode=True)
        sys.exit(0)

    print("NINA-RUHRPOTT Monitor gestartet — NINA-RUHRPOTT (ch2) + DE-NW-NINA-NOT Room")
    while True:
        check()
        time.sleep(300)
