# 2110575_2025_2_IOT_Project

## Smart Chili Vision & IoT Monitoring System

โครงงานนี้เป็นระบบ **Smart Agriculture** ที่ผสานการทำงานระหว่าง  
**Computer Vision**, **IoT Sensors**, และ **On-premise Server (Raspberry Pi)**  
เพื่อใช้ในการตรวจนับจำนวนพริกจากกล้อง และเฝ้าระวังสภาพแวดล้อมแบบเรียลไทม์  
พร้อมบันทึกข้อมูลและแสดงผลผ่าน Dashboard

---

## 📌 Features
- ตรวจนับจำนวนพริกด้วยกล้อง + AI
- รับภาพจาก ESP32-CAM
- ตรวจวัด Temp, Humidity, Light, CO₂, Soil Moisture
- ส่งข้อมูลผ่าน MQTT
- จัดเก็บข้อมูลแบบ On-premise ด้วย InfluxDB  และ SQLite
- Dashboard แสดงผลแบบ Real-time
- รองรับ Actuator (เช่น Relay)

---

## 🏗️ System Architecture

**Sensor Node**
- ESP32 + Sensors  

**Gateway / Server**
- Raspberry Pi  
- Mosquitto (MQTT Broker)  
- InfluxDB  
- Python Subscribers  
- AI Processing & Database Manager
- Raspberry Pi Camera module 3
---

## 📂 Project Structure
