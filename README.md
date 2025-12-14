# 2110575_2025_2_IOT_Project

## Smart Chili Vision & IoT Monitoring System

โครงงานนี้เป็นระบบ **Smart Agriculture** ที่ผสานการทำงานระหว่าง  
**Computer Vision**, **IoT Sensors**, และ **On-premise Server (Raspberry Pi)**  
เพื่อใช้ในการตรวจนับจำนวนพริกจากกล้อง และเฝ้าระวังสภาพแวดล้อมแบบเรียลไทม์  
พร้อมบันทึกข้อมูลและแสดงผลผ่าน Dashboard

---

## Features
- ตรวจนับจำนวนพริกด้วยกล้อง + AI
- รับภาพจาก ESP32-CAM
- ตรวจวัด Temp, Humidity, Light, CO₂, Soil Moisture
- ส่งข้อมูลผ่าน MQTT
- จัดเก็บข้อมูลแบบ On-premise ด้วย InfluxDB  และ SQLite
- Dashboard แสดงผลแบบ Real-time
- รองรับ Actuator (เช่น Relay)

---

## Project Structure

โครงงานแบ่งการทำงานออกเป็น 2 ส่วนหลัก คือ **Publisher (pub)** และ **Subscriber (sub)**  
โดยใช้ **MQTT Broker** เป็นตัวกลางในการสื่อสารข้อมูล

### ESP32
- `pub_esp32.cpp`  
  ทำหน้าที่เป็น **Publisher (pub)**  
  - อ่านค่าจากเซ็นเซอร์บน ESP32  
  - ส่งข้อมูลขึ้น MQTT Broker ผ่าน Topic (เช่น `iot/esp/data`)

---

### raspberryPI_camera
- `pub_sensor_on_pi.py`  
  เป็น **Publisher (pub)** บน Raspberry Pi  
  - อ่านค่าจากเซ็นเซอร์ที่ต่อกับ Raspberry Pi  
  - ส่งข้อมูลไปยัง MQTT Broker

- `publisher_camera.py`  
  เป็น **Publisher (pub)**  
  - เปิดกล้อง
  - ประมวลผลภาพ (Computer Vision)
  - ส่งข้อมูลภาพ / ผลลัพธ์ไปยัง MQTT Broker ผ่าน Topic `iot/camera`

- `subscriber_main_on_pi.py`  
  เป็น **Subscriber (sub)**  
  - รับข้อมูลจาก MQTT Broker  
  - ประมวลผลข้อมูล
  - บันทึกข้อมูลลง InfluxDB

- `Dashboard.py`  
  - แสดงผลข้อมูลจากระบบในรูปแบบ Dashboard  
  - แสดงค่า Sensor และผลจากกล้องแบบ Real-time

---
