# (write only /iot/data and iot/esp/data to InfluxDB)
import json
import base64
import binascii
import sqlite3
from datetime import datetime, timezone
from time import sleep

import paho.mqtt.client as mqtt

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

import RPi.GPIO as GPIO


# -------------------- MQTT --------------------
MQTT_BROKER = "localhost"
MQTT_PORT   = 1883

MQTT_TOPIC_PI     = "/iot/data"        # Pi JSON
MQTT_TOPIC_ESP    = "iot/esp/data"     # ESP32 CSV
MQTT_TOPIC_CAMERA = "iot/camera"       # Camera JSON + image


# -------------------- InfluxDB ----------------
INFLUX_URL    = "http://localhost:8086"
INFLUX_ORG    = "Student"
INFLUX_BUCKET = "iot_data"
INFLUX_TOKEN  = ""


# -------------------- SQLite สำหรับ camera --------------------
CAMERA_DB_PATH = "camera_frames.db"


# -------------------- GPIO --------------------
BUZZER_PIN = 18
RELAY_PIN  = 27
RELAY_ACTIVE_LOW = True


# -------------------- Threshold --------------------
TEMP_ON  = 21.0
TEMP_OFF = 26.0

HUM_ON   = 50.0
HUM_OFF  = 80.0

CO2_ON   = 400.0
CO2_OFF  = 800.0


# -------------------- GLOBAL SENSOR CACHE --------------------
last_temp = None
last_hum  = None
last_co2  = None


# -------------------- Setup GPIO --------------------
GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT)
GPIO.setup(BUZZER_PIN, GPIO.OUT)
GPIO.output(BUZZER_PIN, GPIO.LOW)


# -------------------- Relay Logic --------------------
def update_relay_by_conditions(temp=None, hum=None, co2=None):
    relay_on = False

    if temp is not None and not (TEMP_ON <= temp <= TEMP_OFF):
        relay_on = True

    if hum is not None and not (HUM_ON <= hum <= HUM_OFF):
        relay_on = True

    if co2 is not None and not (CO2_ON <= co2 <= CO2_OFF):
        relay_on = True

    should_state = GPIO.HIGH if relay_on else GPIO.LOW
    current = GPIO.input(RELAY_PIN)

    if current != should_state:
        GPIO.output(RELAY_PIN, should_state)
        print(f"Relay {'ON' if relay_on else 'OFF'} (Temp={temp}, Hum={hum}, CO2={co2})")

        if relay_on:
            pwm = GPIO.PWM(BUZZER_PIN, 1000)
            pwm.start(50)
            sleep(1)
            pwm.stop()
            GPIO.output(BUZZER_PIN, GPIO.LOW)


# -------------------- Camera DB --------------------
def init_camera_db():
    conn = sqlite3.connect(CAMERA_DB_PATH)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        width INTEGER,
        height INTEGER,
        fps REAL,
        chili_count INTEGER,
        jpg BLOB NOT NULL
    )
    """)
    conn.commit()
    conn.close()
    print("Camera SQLite DB ready")


def save_camera_image(jpg_bytes, width, height, fps, chili_count):
    conn = sqlite3.connect(CAMERA_DB_PATH)
    conn.execute(
        "INSERT INTO images (created_at, width, height, fps, chili_count, jpg) VALUES (?, ?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            width,
            height,
            fps,
            chili_count,
            sqlite3.Binary(jpg_bytes),
        )
    )
    conn.commit()
    conn.close()

    print(f"Saved camera frame size={width}x{height}, fps={fps}, chili={chili_count}")


# -------------------- InfluxDB Setup --------------------
try:
    influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = influx_client.write_api(write_options=SYNCHRONOUS)
    print("Connected to InfluxDB")
except Exception as e:
    print("InfluxDB connect error:", e)
    GPIO.cleanup()
    raise SystemExit(1)

init_camera_db()


# -------------------- Helper: write functions --------------------
def write_pi_to_influx(temperature=None, light=None):
    """
    Write Pi data to measurement 'mqtt_data' with tag node='raspi'
    """
    try:
        p = Point("mqtt_data").tag("location", "lab1").tag("node", "raspi")
        if temperature is not None:
            p = p.field("temperature", float(temperature))
        if light is not None:
            p = p.field("light", float(light))
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=p)
        print("Written Pi data to InfluxDB:", {"temperature": temperature, "light": light})
    except Exception as e:
        print("Error writing Pi data to InfluxDB:", e)


def write_esp_to_influx(co2=None, humidity=None, soil=None):
    """
    Write ESP32 data to measurement 'mqtt_data' with tag node='esp32'
    """
    try:
        p = Point("mqtt_data").tag("location", "lab1").tag("node", "esp32")
        if co2 is not None:
            p = p.field("co2", float(co2))
        if humidity is not None:
            p = p.field("humidity", float(humidity))
        if soil is not None:
            p = p.field("soil", float(soil))
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=p)
        print("Written ESP32 data to InfluxDB:", {"co2": co2, "humidity": humidity, "soil": soil})
    except Exception as e:
        print("Error writing ESP32 data to InfluxDB:", e)


# -------------------- MQTT CALLBACK --------------------
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("MQTT connected")
        client.subscribe(MQTT_TOPIC_PI)
        client.subscribe(MQTT_TOPIC_ESP)
        client.subscribe(MQTT_TOPIC_CAMERA)
    else:
        print("MQTT connect failed:", rc)


def on_message(client, userdata, msg):
    global last_temp, last_hum, last_co2

    print("\n=== MQTT MESSAGE ===")
    print("Topic:", msg.topic)

    # ---------------- Camera (do NOT write to Influx) ----------------
    if msg.topic == MQTT_TOPIC_CAMERA:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            print("JSON decode error (Camera):", e)
            print("Raw payload (truncated):", msg.payload[:200], "...")
            return

        cam = payload.get("camera", {}) or {}
        img_b64 = payload.get("image") or payload.get("img")  # support both names

        if not img_b64:
            print("⚠ Camera message has no 'image' field, skip saving image.")
            return

        try:
            decoded = base64.b64decode(img_b64.strip(), validate=True)
        except Exception as e:
            print("⚠ base64 decode error (Camera):", e)
            return

        width  = cam.get("width")
        height = cam.get("height")
        fps    = cam.get("fps")
        chili_count = cam.get("chili_count")

        print(f"Camera -> chili_count={chili_count}, fps={fps}, size={width}x{height}")

        try:
            save_camera_image(decoded, width, height, fps, chili_count)
        except Exception as e:
            print(" Error saving camera image to SQLite:", e)

        # Do NOT write camera metadata to Influx — per request
        return

    # ---------------- Pi JSON ----------------
    if msg.topic == MQTT_TOPIC_PI:
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            print("Pi JSON decode error:", e)
            return

        pi = data.get("pi", {}) or {}
        temp = pi.get("temperature")
        light = pi.get("light")

        # update cache for relay
        try:
            last_temp = float(temp) if temp is not None else None
        except Exception:
            last_temp = None

        try:
            last_light = float(light) if light is not None else None
        except Exception:
            last_light = None

        print(f"Pi -> Temp={last_temp}, Light={last_light}")

        # write ONLY Pi fields to Influx (same measurement "mqtt_data")
        write_pi_to_influx(temperature=last_temp, light=last_light)

        # update relay with freshest values (use cached last_hum/last_co2)
        update_relay_by_conditions(last_temp, last_hum, last_co2)
        return

    # ---------------- ESP32 CSV ----------------
    if msg.topic == MQTT_TOPIC_ESP:
        try:
            parts = msg.payload.decode("utf-8").strip().split(',')
            if len(parts) != 3:
                print("ESP32 CSV format error:", parts)
                return
            co2_val = float(parts[0])
            hum_val = float(parts[1])
            soil_val = float(parts[2])
            last_co2 = co2_val
            last_hum = hum_val
            last_soil = soil_val
        except Exception as e:
            print("❌ ESP32 CSV parse error:", e, "payload:", msg.payload)
            return

        print(f"ESP32 -> CO2={last_co2}, Hum={last_hum}, Soil={last_soil}")

        # write ONLY ESP32 fields to Influx (same measurement "mqtt_data")
        write_esp_to_influx(co2=last_co2, humidity=last_hum, soil=last_soil)

        # update relay with freshest values (use cached last_temp)
        update_relay_by_conditions(last_temp, last_hum, last_co2)
        return


# -------------------- MAIN --------------------
def main():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    print("Connecting to MQTT broker...")
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        GPIO.cleanup()
        print("GPIO cleaned up.")# subscriber_all.py  (write only /iot/data and iot/esp/data to InfluxDB)
import json
import base64
import binascii
import sqlite3
from datetime import datetime, timezone
from time import sleep

import paho.mqtt.client as mqtt

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

import RPi.GPIO as GPIO


# -------------------- MQTT --------------------
MQTT_BROKER = "localhost"
MQTT_PORT   = 1883

MQTT_TOPIC_PI     = "/iot/data"        # Pi JSON
MQTT_TOPIC_ESP    = "iot/esp/data"     # ESP32 CSV
MQTT_TOPIC_CAMERA = "iot/camera"       # Camera JSON + image


# -------------------- InfluxDB ----------------
INFLUX_URL    = "http://localhost:8086"
INFLUX_ORG    = "Student"
INFLUX_BUCKET = "iot_data"
INFLUX_TOKEN  = "vbcRlrUlawg5-2BrLG4gmWIwuaITSvb_96aANkH4CWUDzgiWSEioSs0pd9UbgsjJkHf8PdaUVRa_xLTKbvOwow=="


# -------------------- SQLite สำหรับ camera --------------------
CAMERA_DB_PATH = "camera_frames.db"


# -------------------- GPIO --------------------
BUZZER_PIN = 18
RELAY_PIN  = 27
RELAY_ACTIVE_LOW = True


# -------------------- Threshold --------------------
TEMP_ON  = 21.0
TEMP_OFF = 26.0

HUM_ON   = 50.0
HUM_OFF  = 80.0

CO2_ON   = 400.0
CO2_OFF  = 800.0


# -------------------- GLOBAL SENSOR CACHE --------------------
last_temp = None
last_hum  = None
last_co2  = None


# -------------------- Setup GPIO --------------------
GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT)
GPIO.setup(BUZZER_PIN, GPIO.OUT)
GPIO.output(BUZZER_PIN, GPIO.LOW)


# -------------------- Relay Logic --------------------
def update_relay_by_conditions(temp=None, hum=None, co2=None):
    relay_on = False

    if temp is not None and not (TEMP_ON <= temp <= TEMP_OFF):
        relay_on = True

    if hum is not None and not (HUM_ON <= hum <= HUM_OFF):
        relay_on = True

    if co2 is not None and not (CO2_ON <= co2 <= CO2_OFF):
        relay_on = True

    should_state = GPIO.HIGH if relay_on else GPIO.LOW
    current = GPIO.input(RELAY_PIN)

    if current != should_state:
        GPIO.output(RELAY_PIN, should_state)
        print(f"Relay {'ON' if relay_on else 'OFF'} (Temp={temp}, Hum={hum}, CO2={co2})")

        if relay_on:
            pwm = GPIO.PWM(BUZZER_PIN, 1000)
            pwm.start(50)
            sleep(1)
            pwm.stop()
            GPIO.output(BUZZER_PIN, GPIO.LOW)


# -------------------- Camera DB --------------------
def init_camera_db():
    conn = sqlite3.connect(CAMERA_DB_PATH)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        width INTEGER,
        height INTEGER,
        fps REAL,
        chili_count INTEGER,
        jpg BLOB NOT NULL
    )
    """)
    conn.commit()
    conn.close()
    print("Camera SQLite DB ready")


def save_camera_image(jpg_bytes, width, height, fps, chili_count):
    conn = sqlite3.connect(CAMERA_DB_PATH)
    conn.execute(
        "INSERT INTO images (created_at, width, height, fps, chili_count, jpg) VALUES (?, ?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            width,
            height,
            fps,
            chili_count,
            sqlite3.Binary(jpg_bytes),
        )
    )
    conn.commit()
    conn.close()

    print(f"Saved camera frame size={width}x{height}, fps={fps}, chili={chili_count}")


# -------------------- InfluxDB Setup --------------------
try:
    influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = influx_client.write_api(write_options=SYNCHRONOUS)
    print("Connected to InfluxDB")
except Exception as e:
    print("InfluxDB connect error:", e)
    GPIO.cleanup()
    raise SystemExit(1)

init_camera_db()


# -------------------- Helper: write functions --------------------
def write_pi_to_influx(temperature=None, light=None):
    """
    Write Pi data to measurement 'mqtt_data' with tag node='raspi'
    """
    try:
        p = Point("mqtt_data").tag("location", "lab1").tag("node", "raspi")
        if temperature is not None:
            p = p.field("temperature", float(temperature))
        if light is not None:
            p = p.field("light", float(light))
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=p)
        print("Written Pi data to InfluxDB:", {"temperature": temperature, "light": light})
    except Exception as e:
        print("Error writing Pi data to InfluxDB:", e)


def write_esp_to_influx(co2=None, humidity=None, soil=None):
    """
    Write ESP32 data to measurement 'mqtt_data' with tag node='esp32'
    """
    try:
        p = Point("mqtt_data").tag("location", "lab1").tag("node", "esp32")
        if co2 is not None:
            p = p.field("co2", float(co2))
        if humidity is not None:
            p = p.field("humidity", float(humidity))
        if soil is not None:
            p = p.field("soil", float(soil))
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=p)
        print("Written ESP32 data to InfluxDB:", {"co2": co2, "humidity": humidity, "soil": soil})
    except Exception as e:
        print("Error writing ESP32 data to InfluxDB:", e)


# -------------------- MQTT CALLBACK --------------------
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("MQTT connected")
        client.subscribe(MQTT_TOPIC_PI)
        client.subscribe(MQTT_TOPIC_ESP)
        client.subscribe(MQTT_TOPIC_CAMERA)
    else:
        print("MQTT connect failed:", rc)


def on_message(client, userdata, msg):
    global last_temp, last_hum, last_co2

    print("\n=== MQTT MESSAGE ===")
    print("Topic:", msg.topic)

    # ---------------- Camera (do NOT write to Influx) ----------------
    if msg.topic == MQTT_TOPIC_CAMERA:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            print("JSON decode error (Camera):", e)
            print("Raw payload (truncated):", msg.payload[:200], "...")
            return

        cam = payload.get("camera", {}) or {}
        img_b64 = payload.get("image") or payload.get("img")  # support both names

        if not img_b64:
            print("⚠ Camera message has no 'image' field, skip saving image.")
            return

        try:
            decoded = base64.b64decode(img_b64.strip(), validate=True)
        except Exception as e:
            print("⚠ base64 decode error (Camera):", e)
            return

        width  = cam.get("width")
        height = cam.get("height")
        fps    = cam.get("fps")
        chili_count = cam.get("chili_count")

        print(f"Camera -> chili_count={chili_count}, fps={fps}, size={width}x{height}")

        try:
            save_camera_image(decoded, width, height, fps, chili_count)
        except Exception as e:
            print(" Error saving camera image to SQLite:", e)

        # Do NOT write camera metadata to Influx — per request
        return

    # ---------------- Pi JSON ----------------
    if msg.topic == MQTT_TOPIC_PI:
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            print("Pi JSON decode error:", e)
            return

        pi = data.get("pi", {}) or {}
        temp = pi.get("temperature")
        light = pi.get("light")

        # update cache for relay
        try:
            last_temp = float(temp) if temp is not None else None
        except Exception:
            last_temp = None

        try:
            last_light = float(light) if light is not None else None
        except Exception:
            last_light = None

        print(f"Pi -> Temp={last_temp}, Light={last_light}")

        # write ONLY Pi fields to Influx (same measurement "mqtt_data")
        write_pi_to_influx(temperature=last_temp, light=last_light)

        # update relay with freshest values (use cached last_hum/last_co2)
        update_relay_by_conditions(last_temp, last_hum, last_co2)
        return

    # ---------------- ESP32 CSV ----------------
    if msg.topic == MQTT_TOPIC_ESP:
        try:
            parts = msg.payload.decode("utf-8").strip().split(',')
            if len(parts) != 3:
                print("ESP32 CSV format error:", parts)
                return
            co2_val = float(parts[0])
            hum_val = float(parts[1])
            soil_val = float(parts[2])
            last_co2 = co2_val
            last_hum = hum_val
            last_soil = soil_val
        except Exception as e:
            print("ESP32 CSV parse error:", e, "payload:", msg.payload)
            return

        print(f"ESP32 -> CO2={last_co2}, Hum={last_hum}, Soil={last_soil}")

        # write ONLY ESP32 fields to Influx (same measurement "mqtt_data")
        write_esp_to_influx(co2=last_co2, humidity=last_hum, soil=last_soil)

        # update relay with freshest values (use cached last_temp)
        update_relay_by_conditions(last_temp, last_hum, last_co2)
        return


# -------------------- MAIN --------------------
def main():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    print("Connecting to MQTT broker...")
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        GPIO.cleanup()
        print("GPIO cleaned up.")
