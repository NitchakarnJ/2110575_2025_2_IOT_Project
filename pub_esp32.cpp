#include <Arduino.h>
#include <WiFi.h> // ไลบรารีสำหรับ Wi-Fi
#include <PubSubClient.h> // ไลบรารีสำหรับ MQTT
#include "DHT.h"

// --- 1. กำหนดค่า Wi-Fi ---
const char* ssid = "internet"; // ชื่อ Wi-Fi 
const char* password = "12345789"; // รหัสผ่าน Wi-Fi

// --- 2. กำหนดค่า MQTT ---
// IP Address ของ Raspberry Pi (MQTT Broker)
const char* mqtt_server = ""; // ***IP ของ Raspberry Pi ***
const int mqtt_port = 1883;
const char* mqtt_client_id = "ESP32_Sensor_Publisher";

// Topic สำหรับส่งข้อมูล
const char* mqtt_topic_co2 = "iot/esp/co2";
const char* mqtt_topic_humidity = "iot/esp/humidity";
const char* mqtt_topic_soil = "iot/esp/soil";
const char* mqtt_topic_all = "iot/esp/data"; // Topic สำหรับส่งข้อมูลรวม (CSV)

// --- 3. การกำหนดค่าเซ็นเซอร์ (เหมือนเดิม) ---
// MQ135
#define MQ135_PIN 33

// DHT11
#define DHTPIN 14
#define DHTTYPE DHT11
DHT dht(DHTPIN, DHTTYPE);

// Soil HW-390
#define Soil_PIN 32

// --- 4. การสร้าง Object สำหรับ Wi-Fi และ MQTT ---
WiFiClient espClient;
PubSubClient client(espClient);

// -------------------------------------------------------------------
//                          ฟังก์ชัน Wi-Fi
// -------------------------------------------------------------------
void setup_wifi() {
  delay(10);
  Serial.println();
  Serial.print("Connecting to ");
  Serial.println(ssid);

  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("");
  Serial.println("WiFi connected");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());
}

// -------------------------------------------------------------------
//                          ฟังก์ชัน MQTT
// -------------------------------------------------------------------
void reconnect() {
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection...");
    if (client.connect(mqtt_client_id)) {
      Serial.println("connected");
    } else {
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" try again in 5 seconds");
      delay(5000);
    }
  }
}

// -------------------------------------------------------------------
//                          Setup
// -------------------------------------------------------------------
void setup()
{
  Serial.begin(115200);

  setup_wifi();

  client.setServer(mqtt_server, mqtt_port);

  pinMode(Soil_PIN, INPUT);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);

  dht.begin();

  Serial.println("ESP32 MQTT Publisher Ready...");
}

// -------------------------------------------------------------------
//                          Loop
// -------------------------------------------------------------------
void loop()
{
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  // -------- 1. อ่านค่าเซ็นเซอร์ทั้งหมด --------
  int mq135Value = analogRead(MQ135_PIN);
  float humidity = dht.readHumidity();
  int SoilValue = analogRead(Soil_PIN);

  // ตรวจสอบค่า DHT (humidity)
  if (isnan(humidity)) {
    Serial.println("DHT11 Error: ไม่สามารถอ่านค่าได้, ไม่ส่งค่านี้");
  } else {
    // -------- 2. สร้าง String สำหรับส่ง (CSV) --------
    // รูปแบบ CSV: CO2_Value,Humidity,Soil_Value
    String payload = String(mq135Value) + "," + String(humidity) + "," + String(SoilValue);
    
    // -------- 3. เผยแพร่ (Publish) ข้อมูล --------
    client.publish(mqtt_topic_all, payload.c_str());
    Serial.print("Published to ");
    Serial.print(mqtt_topic_all);
    Serial.print(": ");
    Serial.println(payload);
  }

  Serial.print("CO2: ");
  Serial.print(mq135Value);
  Serial.print(" | Humidity: ");
  Serial.print(humidity);
  Serial.print(" | Soil: ");
  Serial.println(SoilValue);

  delay(5000); // ส่งทุก 5 วินาที
}
