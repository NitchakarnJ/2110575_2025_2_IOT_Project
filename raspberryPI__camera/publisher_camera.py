# publisher_camera.py

from flask import Flask, Response, render_template_string, jsonify
import cv2
import time
from datetime import datetime
from picamera2 import Picamera2
import json
import base64
import paho.mqtt.client as mqtt

# ---- YOLO (ตรวจพริก) ----
from ultralytics import YOLO
model = YOLO("best.pt")           # วางไฟล์โมเดลไว้โฟลเดอร์เดียวกัน
CLASS_NAMES = model.names

app = Flask(__name__)
font = cv2.FONT_HERSHEY_SIMPLEX

# ---- ตัวแปรสถานะล่าสุดสำหรับโชว์บนเว็บ (/stats) ----
LAST_COUNT = 0
LAST_FPS = 0.0
LAST_W = 0
LAST_H = 0
LAST_MQTT_AT = None  # เวลา ISO ล่าสุดที่ส่ง MQTT สำเร็จ

# ---- MQTT CONFIG (ส่งข้อมูลกล้อง + รูปภาพ) ----
MQTT_BROKER = "localhost"   # ถ้า Mosquitto รันบน Pi ตัวนี้
MQTT_PORT = 1883
MQTT_TOPIC = "iot/camera"   # topic ที่ใช้ส่ง
MQTT_INTERVAL = 10.0        # ✅ ส่ง MQTT ทุก 10 วินาที

mqtt_client = mqtt.Client()
try:
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_start()
    print(f"✅ MQTT connected to {MQTT_BROKER}:{MQTT_PORT}, topic '{MQTT_TOPIC}'")
except Exception as e:
    print("❌ MQTT connect error:", e)
    mqtt_client = None  # กัน error ถ้าต่อไม่ได้

# ------------ YOLO ตรวจพริก ------------
def process_img(img):
    global LAST_COUNT

    # ทำให้เป็น BGR 3 แชนเนลเสมอ (สำหรับ OpenCV/YOLO)
    if img.ndim == 3 and img.shape[2] == 4:
        bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    else:
        bgr = img

    results = model(bgr, imgsz=640, conf=0.6, verbose=False)
    r0 = results[0]

    # จำนวนพริกต่อเฟรม
    per_frame_count = 0
    if r0.boxes is not None and r0.boxes.cls is not None:
        per_frame_count = len(r0.boxes.cls)

    LAST_COUNT = per_frame_count

    annotated = r0.plot(conf=True)  # วาดกรอบ+label+conf แล้วคืนภาพ BGR
    cv2.putText(annotated, f"Chili count: {per_frame_count}",
                (7, 110), font, 1, (0, 0, 255), 3, cv2.LINE_AA)
    return annotated, per_frame_count

# ------------ สตรีมกล้อง + ส่ง MQTT (data + image) ------------
def generate_frames():
    global LAST_FPS, LAST_W, LAST_H, LAST_MQTT_AT

    prev_time = time.time()
    picam2 = Picamera2()
    picam2.configure(picam2.create_preview_configuration(
        main={"format": 'XRGB8888', "size": (640, 480)}
    ))
    picam2.start()

    last_mqtt = 0.0     # ใช้ control ความถี่ในการส่ง MQTT

    while True:
        frame = picam2.capture_array()
        height, width, channels = frame.shape
        LAST_W, LAST_H = width, height

        now = time.time()
        dt = max(now - prev_time, 1e-6)
        fps_num = 1.0 / dt
        fps_text = str(int(fps_num))
        prev_time = now
        LAST_FPS = fps_num

        # ตรวจพริก
        frame, per_frame_count = process_img(frame)

        # overlay ขนาด + FPS
        text = f"{width}x{height} | fps:{fps_text}"
        cv2.putText(frame, text, (7, 70), font, 1, (100, 255, 0), 3, cv2.LINE_AA)

        # เข้ารหัส JPEG
        ok, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            continue
        frame_bytes = buffer.tobytes()

        # ✅ ส่งข้อมูล + รูปภาพขึ้น MQTT (จำกัดทุก 10 วินาที)
        if mqtt_client is not None and (now - last_mqtt) >= MQTT_INTERVAL:
            try:
                img_b64 = base64.b64encode(frame_bytes).decode("ascii")
                payload = {
                    "camera": {
                        "chili_count": int(per_frame_count),
                        "fps": float(fps_num),
                        "width": int(width),
                        "height": int(height),
                    },
                    "image": img_b64
                }
                mqtt_client.publish(MQTT_TOPIC, json.dumps(payload))
                LAST_MQTT_AT = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                # print("MQTT sent", LAST_MQTT_AT)
            except Exception as e:
                print("MQTT publish error:", e)
            last_mqtt = now

        # ส่งไปเป็น MJPEG stream สำหรับเว็บ
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# ------------------------ Routes ------------------------
@app.route('/')
def index():
    html_code = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Raspberry Pi Camera Stream</title>
        <style>
          body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial;
                 margin: 24px; background:#0f2027; color:#eaf2f8; }
          .wrap { max-width: 980px; margin: auto; }
          h1 { margin: 0 0 6px; }
          .sub { color: #a5b4c0; margin-bottom: 16px; }
          .card { background: rgba(255,255,255,0.08);
                  border: 1px solid rgba(255,255,255,0.15);
                  border-radius: 14px; padding: 14px; margin-bottom: 12px;}
          a { color:#67e8f9; text-decoration:none; }
          .stats { display:flex; gap:16px; flex-wrap:wrap;
                   font-size: 14px; color:#a5b4c0;}
          .stats span { font-weight:700; color:#eaf2f8; }
        </style>
    </head>
    <body>
        <div class="wrap">
            <h1>🌶️ Chili Detector — Live</h1>
            <div class="sub">
              Ultralytics YOLO on Raspberry Pi camera (MJPEG stream)
              — MQTT topic: <code>iot/camera</code> (every 10 seconds)
            </div>

            <div class="card">
                <img src="{{ url_for('video_feed') }}" width="640" height="480">
            </div>

            <div class="card">
              <div class="stats">
                <div>Chili count (per frame): <span id="count">—</span></div>
                <div>Resolution: <span id="res">—</span></div>
                <div>FPS: <span id="fps">—</span></div>
                <div>Last MQTT sent: <span id="sent">—</span></div>
              </div>
            </div>
        </div>

        <script>
          async function refreshStats(){
            try{
              const r = await fetch('/stats', {cache:'no-store'});
              const s = await r.json();
              document.getElementById('count').textContent = s.count ?? '—';
              document.getElementById('res').textContent =
                (s.width && s.height) ? (s.width + '×' + s.height) : '—';
              document.getElementById('fps').textContent =
                s.fps ? s.fps.toFixed(1) : '—';
              document.getElementById('sent').textContent =
                s.last_mqtt_at || '—';
            }catch(e){}
          }
          setInterval(refreshStats, 800);
          refreshStats();
        </script>
    </body>
    </html>
    """
    return render_template_string(html_code)

@app.route('/stats')
def stats():
    return jsonify({
        "count": LAST_COUNT,
        "fps": float(LAST_FPS),
        "width": int(LAST_W),
        "height": int(LAST_H),
        "last_mqtt_at": LAST_MQTT_AT
    })

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

# ------------------------ Main ------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
