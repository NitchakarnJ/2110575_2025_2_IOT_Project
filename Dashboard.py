from flask import Flask, jsonify, render_template_string
from influxdb_client import InfluxDBClient
import paho.mqtt.client as mqtt
import json
import threading
from datetime import datetime

app = Flask(__name__)

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
PI_IP         = "10.243.6.104"       # IP ของ Raspberry Pi
INFLUX_URL    = f"http://{PI_IP}:8086"
INFLUX_TOKEN  = "BMvUDwq7stNMmgGJPatqIoPWWH8KJ1tqKqN3goGYCOG1uXGWTTGfeYkhO_AbNgvDF9EAtxwfCHGSeP0J5JrFXA=="
INFLUX_ORG    = "Student"
INFLUX_BUCKET = "iot_data"

MQTT_BROKER   = "localhost"          # ถ้า run บน Pi ใช้ localhost, ถ้า run บน PC ใส่ IP Pi
MQTT_PORT     = 1883

# ==========================================
# 💾 GLOBAL VARIABLES (สำหรับ Live Data)
# ==========================================
# ตัวแปรนี้จะถูกอัปเดตทันทีที่ MQTT ส่งข้อมูลมา
current_data = {
    "pi_temp": None, "pi_light": None, "pi_update": "-",
    "esp_co2": None, "esp_hum": None, "esp_soil": None, "esp_update": "-",
    "cam_img": None, "cam_count": 0, "cam_fps": 0, "cam_update": "-"
}

# ==========================================
# 📡 MQTT SUBSCRIBER SETUP
# ==========================================
def on_connect(client, userdata, flags, rc):
    print(f"✅ MQTT Connected with result code {rc}")
    client.subscribe("/iot/data")
    client.subscribe("iot/esp/data")
    client.subscribe("iot/camera")

def on_message(client, userdata, msg):
    global current_data
    topic = msg.topic
    payload = msg.payload
    now_str = datetime.now().strftime("%H:%M:%S")

    try:
        if topic == "/iot/data":
            data = json.loads(payload.decode()).get("pi", {})
            current_data["pi_temp"] = data.get("temperature")
            current_data["pi_light"] = data.get("light")
            current_data["pi_update"] = now_str
            
        elif topic == "iot/esp/data":
            # CSV format: co2,humidity,soil
            parts = payload.decode().strip().split(",")
            if len(parts) >= 3:
                current_data["esp_co2"] = float(parts[0])
                current_data["esp_hum"] = float(parts[1])
                current_data["esp_soil"] = float(parts[2])
                current_data["esp_update"] = now_str

        elif topic == "iot/camera":
            data = json.loads(payload.decode())
            cam = data.get("camera", {})
            current_data["cam_img"] = data.get("image") # Base64 string
            current_data["cam_count"] = cam.get("chili_count", 0)
            current_data["cam_fps"] = cam.get("fps", 0)
            current_data["cam_update"] = now_str

    except Exception as e:
        print(f"❌ MQTT Error ({topic}): {e}")

# รัน MQTT ใน Background Thread ไม่ให้บล็อก Flask
def start_mqtt():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except Exception as e:
        print(f"❌ MQTT Connection Failed: {e}")

threading.Thread(target=start_mqtt, daemon=True).start()

# ==========================================
# 🗄️ INFLUXDB SETUP (สำหรับ History Data)
# ==========================================
influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
query_api = influx_client.query_api()

# ==========================================
# 🌐 API ROUTES
# ==========================================

@app.route('/api/live')
def api_live():
    """ส่งข้อมูลล่าสุดที่เก็บไว้ใน RAM (จาก MQTT)"""
    return jsonify(current_data)

@app.route('/api/history')
def api_history():
    """ดึงข้อมูลย้อนหลัง 1 ชม. จาก InfluxDB"""
    query = f'''
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -1h)
      |> filter(fn: (r) => r._measurement == "mqtt_data")
      |> filter(fn: (r) => r._field == "temperature" or r._field == "humidity" or r._field == "co2" or r._field == "light" or r._field == "soil")
      |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")
      |> keep(columns: ["_time", "temperature", "humidity", "co2", "light", "soil"])
    '''
    try:
        tables = query_api.query(org=INFLUX_ORG, query=query)
        data = []
        for table in tables:
            for record in table.records:
                data.append({
                    "time": record.get_time().isoformat(),
                    "temp": record.values.get("temperature"),
                    "hum": record.values.get("humidity"),
                    "co2": record.values.get("co2"),
                    "light": record.values.get("light"),
                    "soil": record.values.get("soil")
                })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/')
def index():
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Smart Farm Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: sans-serif; background: #0f172a; color: #f1f5f9; padding: 20px; margin: 0; }
            
            /* TAB NAVIGATION */
            .tabs { display: flex; gap: 10px; margin-bottom: 20px; border-bottom: 2px solid #334155; padding-bottom: 10px; }
            .tab-btn {
                background: #1e293b; color: #94a3b8; border: none; padding: 10px 20px;
                cursor: pointer; font-size: 16px; border-radius: 8px 8px 0 0;
            }
            .tab-btn.active { background: #38bdf8; color: #0f172a; font-weight: bold; }
            .tab-content { display: none; animation: fadeIn 0.5s; }
            .tab-content.active { display: block; }
            @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

            /* LIVE MONITOR STYLES */
            .live-grid { display: flex; flex-wrap: wrap; gap: 20px; }
            .card { background: #1e293b; padding: 20px; border-radius: 12px; flex: 1; min-width: 250px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
            .card h3 { margin-top: 0; color: #38bdf8; border-bottom: 1px solid #334155; padding-bottom: 10px; }
            .val-row { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 1.1em; }
            .val-data { color: #fbbf24; font-weight: bold; }
            .camera-box { text-align: center; }
            .camera-box img { max-width: 100%; border-radius: 8px; border: 2px solid #ef4444; }

            /* HISTORY CHART STYLES */
            .charts-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 20px; }
            .chart-box { background: #1e293b; padding: 15px; border-radius: 12px; }
        </style>
    </head>
    <body>

        <h2 style="text-align:center;">🚀 IoT Smart Farm Monitor</h2>

        <div class="tabs">
            <button class="tab-btn active" onclick="openTab('live', this)">🔴 Live Monitor</button>
            <button class="tab-btn" onclick="openTab('history', this)">📊 History Graph</button>
        </div>

        <div id="live" class="tab-content active">
            <div class="live-grid">
                <div class="card camera-box" style="flex: 2;">
                    <h3>📷 AI Camera Feed</h3>
                    <img id="cam-img" src="" alt="Waiting for Camera stream...">
                    <div style="margin-top:10px;">
                        <span>Chili Found: <b id="cam-count" style="color:#ef4444; font-size:1.2em;">0</b></span> |
                        <span>FPS: <b id="cam-fps">0</b></span>
                    </div>
                </div>

                <div class="card">
                    <h3>🌡️ Sensor Values</h3>
                    <div class="val-row"><span>Temp (Pi)</span> <span id="pi-temp" class="val-data">-</span></div>
                    <div class="val-row"><span>Light (Pi)</span> <span id="pi-light" class="val-data">-</span></div>
                    <div class="val-row"><span>CO2 (ESP)</span> <span id="esp-co2" class="val-data">-</span></div>
                    <div class="val-row"><span>Humidity</span> <span id="esp-hum" class="val-data">-</span></div>
                    <div class="val-row"><span>Soil Moist</span> <span id="esp-soil" class="val-data">-</span></div>
                    <hr style="border-color:#334155;">
                    <small style="color:#94a3b8;">Last Update: <span id="last-update">-</span></small>
                </div>
            </div>
        </div>

        <div id="history" class="tab-content">
            <div style="text-align:right; margin-bottom:10px;">
                <button onclick="loadHistory()" style="background:#38bdf8; border:none; padding:8px 15px; border-radius:5px; cursor:pointer;">🔄 Refresh Graphs</button>
            </div>
            <div class="charts-grid">
                <div class="chart-box"><canvas id="cTemp"></canvas></div>
                <div class="chart-box"><canvas id="cHum"></canvas></div>
                <div class="chart-box"><canvas id="cCO2"></canvas></div>
                <div class="chart-box"><canvas id="cLight"></canvas></div>
                <div class="chart-box"><canvas id="cSoil"></canvas></div>
            </div>
        </div>

        <script>
            // --- TAB SWITCHING LOGIC ---
            function openTab(tabName, btn) {
                document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
                document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
                document.getElementById(tabName).classList.add('active');
                btn.classList.add('active');
                
                if(tabName === 'history') loadHistory(); // Auto load history when tab clicked
            }

            // --- 1. LIVE DATA LOGIC ---
            async function updateLive() {
                try {
                    const res = await fetch('/api/live');
                    const d = await res.json();

                    // Sensors
                    document.getElementById('pi-temp').innerText  = d.pi_temp ? d.pi_temp.toFixed(1) + ' °C' : '-';
                    document.getElementById('pi-light').innerText = d.pi_light ? d.pi_light.toFixed(0) + ' Lux' : '-';
                    document.getElementById('esp-co2').innerText  = d.esp_co2 ? d.esp_co2.toFixed(0) + ' ppm' : '-';
                    document.getElementById('esp-hum').innerText  = d.esp_hum ? d.esp_hum.toFixed(1) + ' %' : '-';
                    document.getElementById('esp-soil').innerText = d.esp_soil ? d.esp_soil.toFixed(1) + ' %' : '-';
                    document.getElementById('last-update').innerText = d.esp_update;

                    // Camera
                    if(d.cam_img) document.getElementById('cam-img').src = "data:image/jpeg;base64," + d.cam_img;
                    document.getElementById('cam-count').innerText = d.cam_count;
                    document.getElementById('cam-fps').innerText = d.cam_fps.toFixed(1);

                } catch(e) { console.error("Live fetch error", e); }
            }
            setInterval(updateLive, 1000); // Call every 1 second

            // --- 2. HISTORY CHART LOGIC ---
            let charts = {};
            
            function initChart(id, label, color, unit) {
                return new Chart(document.getElementById(id), {
                    type: 'line',
                    data: { labels: [], datasets: [{ label: label, data: [], borderColor: color, backgroundColor: color+'20', fill: true, tension: 0.3 }] },
                    options: { responsive: true, scales: { y: { title: { display:true, text: unit } } } }
                });
            }

            async function loadHistory() {
                // Init charts if not exists
                if(Object.keys(charts).length === 0) {
                    charts.temp = initChart('cTemp', 'Temperature', '#facc15', '°C');
                    charts.hum  = initChart('cHum', 'Humidity', '#38bdf8', '%');
                    charts.co2  = initChart('cCO2', 'CO2', '#a3e635', 'ppm');
                    charts.light= initChart('cLight', 'Light', '#fbbf24', 'Lux');
                    charts.soil = initChart('cSoil', 'Soil Moisture', '#c084fc', '%');
                }

                try {
                    const res = await fetch('/api/history');
                    const data = await res.json();
                    if(data.error) return alert("DB Error: " + data.error);

                    const times = data.map(d => new Date(d.time).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}));
                    
                    const update = (key, raw) => {
                        charts[key].data.labels = times;
                        charts[key].data.datasets[0].data = raw;
                        charts[key].update();
                    };

                    update('temp', data.map(d => d.temp));
                    update('hum', data.map(d => d.hum));
                    update('co2', data.map(d => d.co2));
                    update('light', data.map(d => d.light));
                    update('soil', data.map(d => d.soil));
                    
                } catch(e) { console.error("History fetch error", e); }
            }
        </script>
    </body>
    </html>
    ''')

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5001, debug=True)
