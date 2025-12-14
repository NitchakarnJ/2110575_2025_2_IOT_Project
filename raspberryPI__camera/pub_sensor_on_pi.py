import os
import glob
import time
import smbus
import json
import paho.mqtt.client as mqtt

# ---------------- KY-001 ----------------
os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')

base_dir = '/sys/bus/w1/devices/'
device_folders = glob.glob(base_dir + '28*')
if not device_folders:
    raise RuntimeError("ไม่พบ KY-001 (ไม่มีโฟลเดอร์ 28* ใน /sys/bus/w1/devices/)")
device_folder = device_folders[0]
device_file = device_folder + '/w1_slave'

def read_temp_raw():
    try:
        with open(device_file, 'r') as f:
            return f.readlines()
    except Exception as e:
        print("KY-001 read_raw error:", e)
        return []

def read_temp():
    max_retry = 5

    lines = read_temp_raw()
    retry = 0

    # ถ้าไม่มีบรรทัดเลย หรือมีน้อยกว่า 2 บรรทัด → retry
    while (not lines or len(lines) < 2) and retry < max_retry:
        print(f"⚠ KY-001: no data (len={len(lines)}), retry {retry+1}/{max_retry}")
        time.sleep(0.2)
        lines = read_temp_raw()
        retry += 1

    if not lines or len(lines) < 2:
        print("KY-001: still no valid data after retries, return None")
        return None

    # ตรวจ CRC (YES) แบบมี retry
    retry = 0
    while not lines[0].strip().endswith('YES') and retry < max_retry:
        print(f"KY-001: CRC not YES, retry {retry+1}/{max_retry}")
        time.sleep(0.2)
        lines = read_temp_raw()
        if not lines or len(lines) < 2:
            print("KY-001: no data while checking CRC, return None")
            return None
        retry += 1

    if not lines[0].strip().endswith('YES'):
        print("KY-001: CRC still not YES after retries, return None")
        return None

    # parse ค่า t=
    equals_pos = lines[1].find('t=')
    if equals_pos != -1:
        temp_str = lines[1][equals_pos + 2:]
        try:
            temp_c = float(temp_str) / 1000.0
            return temp_c
        except ValueError:
            print("KY-001: invalid temp string:", temp_str)
            return None

    print("KY-001: 't=' not found in", lines[1].strip())
    return None

# ---------------- BH1750 ----------------
bus = smbus.SMBus(1)
BH1750_ADDR = 0x23
CONTINUOUS_HIGH_RES_MODE = 0x10

def read_light():
    """ อ่านค่าความสว่างจาก BH1750 หน่วย lux """
    try:
        bus.write_byte(BH1750_ADDR, CONTINUOUS_HIGH_RES_MODE)
        time.sleep(0.2)
        data = bus.read_i2c_block_data(BH1750_ADDR, 0x00, 2)
        lux = (data[0] << 8 | data[1]) / 1.2
        return lux
    except Exception as e:
        print("BH1750 read error:", e)
        return None

# ---------------- MQTT ----------------
MQTT_BROKER = "localhost"  # mosquitto รันบน Pi ตัวนี้
MQTT_PORT = 1883
MQTT_TOPIC = "/iot/data"

mqtt_client = mqtt.Client()
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.loop_start()

print("Pi sensor publisher (KY001 + BH1750) -> MQTT /iot/data ready...")

# ---------------- Main Loop ----------------
try:
    while True:
        # อ่านเซนเซอร์บน Raspberry Pi
        pi_temp = read_temp()  # °C
        lux = read_light()     # lux

        # เตรียม payload ส่ง MQTT
        payload = {
            "pi": {
                "temperature": pi_temp,
                "light": lux
            }
        }

        # ส่ง MQTT
        try:
            mqtt_client.publish(MQTT_TOPIC, json.dumps(payload))
        except Exception as e:
            print("MQTT publish error:", e)

        
        temp_str = f"{pi_temp:.2f} °C" if pi_temp is not None else "N/A"
        lux_str = f"{lux:.2f} lux" if lux is not None else "N/A"
        print(f"PUB /iot/data | Pi -> Temp: {temp_str} | Light: {lux_str}")

        
        time.sleep(2.0)

except KeyboardInterrupt:
    print("\nExiting...")
finally:
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
