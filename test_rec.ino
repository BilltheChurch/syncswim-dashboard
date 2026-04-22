#include <M5StickCPlus2.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

#define NODE_NAME "NODE_A1"
#define SERVICE_UUID        "12345678-1234-1234-1234-123456789abc"
#define CHARACTERISTIC_UUID "abcd1234-ab12-cd34-ef56-abcdef123456"
// Secondary characteristic — server writes here to tell the M5 which
// set number the server just allocated. Firmware uses the written
// value on its display so the coach sees the same number the server
// stored on disk (DEVLOG: B-protocol sync).
#define SETNUM_CHARACTERISTIC_UUID "abcd5678-ab12-cd34-ef56-abcdef123456"

BLECharacteristic *pCharacteristic;
BLECharacteristic *pSetnumChar;
BLEServer *pServer;
volatile int displayedSetNumber = 0;   // value received from Python (server-truth)
volatile bool deviceConnected = false;
volatile bool recording = false;
int setNumber = 0;
unsigned long recStartTime = 0;
int loopCount = 0;
unsigned long lastIMUTime = 0;
const unsigned long IMU_INTERVAL_MS = 10;  // 10ms = 100Hz target (IMU gives ~70Hz real)

// ─── Batch BLE protocol ───────────────────────────────────
#define BATCH_SIZE 3

struct __attribute__((packed)) IMUReading {
    uint32_t timestamp;
    int16_t ax, ay, az;   // accel × 1000
    int16_t gx, gy, gz;   // gyro  × 10
};

IMUReading batchBuffer[BATCH_SIZE];
int batchIndex = 0;

M5Canvas canvas(&StickCP2.Display);

// Color palette
const uint16_t COL_BG       = 0x18E3;  // dark blue-gray
const uint16_t COL_BAR      = 0x1082;  // darker bar
const uint16_t COL_WHITE    = TFT_WHITE;
const uint16_t COL_GRAY     = 0xB596;  // light gray
const uint16_t COL_CYAN     = 0x07FF;  // cyan for accel
const uint16_t COL_AMBER    = 0xFE60;  // amber for gyro
const uint16_t COL_GREEN    = 0x07E0;  // green accent
const uint16_t COL_RED      = 0xF800;  // red accent
const uint16_t COL_REC_BG   = 0x8000;  // dark red for rec bar
const uint16_t COL_IDLE_BG  = 0x0320;  // dark green for idle bar

// Defer re-advertising to the main loop so BLE callbacks stay non-blocking.
// Blocking in onDisconnect() (with delay(500)) can freeze the BLE stack and
// has been observed to leave the device stuck — especially after an unclean
// Python-side disconnect (DEVLOG #16).
volatile bool needRestartAdvertising = false;

class MyServerCallbacks : public BLEServerCallbacks {
    void onConnect(BLEServer *s) { deviceConnected = true; }
    void onDisconnect(BLEServer *s) {
        deviceConnected = false;
        needRestartAdvertising = true;   // handled in loop()
    }
};

// Receive the server-assigned set number from Python.
// Use raw-pointer API (getData/getLength) — newer ESP32 Arduino cores
// (3.x) changed getValue() to return Arduino String instead of
// std::string, which breaks std::string assignment. getData()/getLength()
// has been stable across all ESP32 BLE versions.
class MySetnumCallbacks : public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic *c) {
        uint8_t *data = c->getData();
        size_t len = c->getLength();
        if (data != nullptr && len >= 1) {
            displayedSetNumber = data[0];
        }
    }
};

// Watchdog: if we're not connected AND haven't kicked advertising in a
// while, force it on anyway. This is a self-heal in case onDisconnect
// never fires (e.g. the central died ungracefully and our link layer is
// stuck mid-supervision). After this window the host can find us again
// without requiring a manual M5 power-cycle.
unsigned long lastAdvCheck = 0;
const unsigned long ADV_WATCHDOG_MS = 3000;  // check every 3 seconds

void setup() {
    auto cfg = M5.config();
    StickCP2.begin(cfg);
    StickCP2.Display.setRotation(1);
    StickCP2.Imu.begin();

    canvas.createSprite(240, 135);

    BLEDevice::init(NODE_NAME);
    pServer = BLEDevice::createServer();
    pServer->setCallbacks(new MyServerCallbacks());
    BLEService *pService = pServer->createService(SERVICE_UUID);
    pCharacteristic = pService->createCharacteristic(
        CHARACTERISTIC_UUID,
        BLECharacteristic::PROPERTY_NOTIFY
    );
    pCharacteristic->addDescriptor(new BLE2902());

    // Server-assigned set-number characteristic (write from central)
    pSetnumChar = pService->createCharacteristic(
        SETNUM_CHARACTERISTIC_UUID,
        BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_READ
    );
    pSetnumChar->setCallbacks(new MySetnumCallbacks());
    uint8_t init_val = 0;
    pSetnumChar->setValue(&init_val, 1);

    pService->start();
    pServer->getAdvertising()->start();
}

void drawStatusBar() {
    // Top bar background
    canvas.fillRect(0, 0, 240, 22, COL_BAR);

    // Node name (left)
    canvas.setTextSize(1);
    canvas.setTextColor(COL_WHITE);
    canvas.setCursor(6, 6);
    canvas.setTextSize(1);
    canvas.printf("%s", NODE_NAME);

    // BLE status (middle) - prominent indicator
    uint16_t bleCol = deviceConnected ? COL_GREEN : COL_RED;
    canvas.fillCircle(120, 11, 5, bleCol);
    canvas.setTextColor(bleCol);
    canvas.setCursor(129, 6);
    canvas.printf(deviceConnected ? "LINK" : "----");

    // Battery (right)
    int batt = StickCP2.Power.getBatteryLevel();
    uint16_t battCol = batt > 20 ? COL_GREEN : COL_RED;
    // Battery icon outline
    canvas.drawRect(200, 5, 24, 12, battCol);
    canvas.fillRect(224, 8, 3, 6, battCol);
    // Battery fill
    int fillW = (int)(20.0 * batt / 100.0);
    if (fillW > 0) canvas.fillRect(202, 7, fillW, 8, battCol);
    // Percentage text
    canvas.setTextColor(COL_GRAY);
    canvas.setCursor(175, 6);
    canvas.printf("%d%%", batt);
}

void drawIMUData(float ax, float ay, float az, float gx, float gy, float gz) {
    int y0 = 28;

    // Accel section
    canvas.setTextColor(COL_CYAN);
    canvas.setCursor(6, y0);
    canvas.printf("ACCEL");
    canvas.drawFastHLine(6, y0 + 10, 108, COL_CYAN);

    canvas.setTextColor(COL_WHITE);
    canvas.setCursor(6, y0 + 16);
    canvas.printf("X");
    canvas.setTextColor(COL_GRAY);
    canvas.setCursor(18, y0 + 16);
    canvas.printf("%+.2f", ax);

    canvas.setTextColor(COL_WHITE);
    canvas.setCursor(6, y0 + 30);
    canvas.printf("Y");
    canvas.setTextColor(COL_GRAY);
    canvas.setCursor(18, y0 + 30);
    canvas.printf("%+.2f", ay);

    canvas.setTextColor(COL_WHITE);
    canvas.setCursor(6, y0 + 44);
    canvas.printf("Z");
    canvas.setTextColor(COL_GRAY);
    canvas.setCursor(18, y0 + 44);
    canvas.printf("%+.2f", az);

    // Divider line
    canvas.drawFastVLine(120, y0, 60, 0x3186);

    // Gyro section
    canvas.setTextColor(COL_AMBER);
    canvas.setCursor(128, y0);
    canvas.printf("GYRO");
    canvas.drawFastHLine(128, y0 + 10, 108, COL_AMBER);

    canvas.setTextColor(COL_WHITE);
    canvas.setCursor(128, y0 + 16);
    canvas.printf("X");
    canvas.setTextColor(COL_GRAY);
    canvas.setCursor(140, y0 + 16);
    canvas.printf("%+6.1f", gx);

    canvas.setTextColor(COL_WHITE);
    canvas.setCursor(128, y0 + 30);
    canvas.printf("Y");
    canvas.setTextColor(COL_GRAY);
    canvas.setCursor(140, y0 + 30);
    canvas.printf("%+6.1f", gy);

    canvas.setTextColor(COL_WHITE);
    canvas.setCursor(128, y0 + 44);
    canvas.printf("Z");
    canvas.setTextColor(COL_GRAY);
    canvas.setCursor(140, y0 + 44);
    canvas.printf("%+6.1f", gz);

    // Units
    canvas.setTextColor(0x4A69);
    canvas.setCursor(80, y0);
    canvas.printf("g");
    canvas.setCursor(210, y0);
    canvas.printf("d/s");
}

void drawRecBar() {
    int y0 = 110;

    if (recording) {
        canvas.fillRect(0, y0, 240, 25, COL_REC_BG);
        // Blinking dot
        if ((millis() / 500) % 2 == 0) {
            canvas.fillCircle(14, y0 + 12, 5, COL_RED);
        }
        canvas.setTextColor(COL_WHITE);
        canvas.setCursor(24, y0 + 6);
        unsigned long elapsed = (millis() - recStartTime) / 1000;
        int mins = elapsed / 60;
        int secs = elapsed % 60;
        canvas.setTextSize(2);
        // Prefer the server-assigned number (authoritative: matches
        // what's actually saved in data/). Fall back to local count
        // if server hasn't told us yet (no BLE link, first 100ms).
        int shownNum = displayedSetNumber > 0 ? displayedSetNumber : setNumber;
        canvas.printf("REC #%d", shownNum);
        canvas.setTextSize(1);
        canvas.setTextColor(COL_GRAY);
        canvas.setCursor(180, y0 + 8);
        canvas.printf("%02d:%02d", mins, secs);
    } else {
        canvas.fillRect(0, y0, 240, 25, COL_IDLE_BG);
        canvas.setTextColor(COL_GREEN);
        canvas.setCursor(6, y0 + 6);
        canvas.setTextSize(2);
        canvas.printf("READY");
        canvas.setTextSize(1);
        canvas.setTextColor(COL_GRAY);
        canvas.setCursor(140, y0 + 8);
        canvas.printf("Press A start");
    }
    canvas.setTextSize(1);
}

void loop() {
    StickCP2.update();

    // Handle deferred re-advertising (from onDisconnect)
    if (needRestartAdvertising) {
        needRestartAdvertising = false;
        pServer->getAdvertising()->start();
    }

    // Watchdog: force-restart advertising every ADV_WATCHDOG_MS while
    // not connected. Covers the case where onDisconnect never fires
    // because the host vanished ungracefully (Python crash, laptop sleep).
    unsigned long tNow = millis();
    if (!deviceConnected && (tNow - lastAdvCheck > ADV_WATCHDOG_MS)) {
        lastAdvCheck = tNow;
        pServer->getAdvertising()->stop();
        pServer->getAdvertising()->start();
    }

    if (StickCP2.BtnA.wasPressed()) {
        recording = !recording;
        if (recording) {
            setNumber++;
            recStartTime = millis();
            StickCP2.Speaker.tone(2000, 100);
        } else {
            StickCP2.Speaker.tone(1000, 50);
            delay(100);
            StickCP2.Speaker.tone(1000, 50);
        }
    }

    // Read IMU only when interval has elapsed (avoids duplicate readings)
    unsigned long now = millis();
    if (now - lastIMUTime >= IMU_INTERVAL_MS) {
        lastIMUTime = now;

        float ax, ay, az, gx, gy, gz;
        StickCP2.Imu.getAccel(&ax, &ay, &az);
        StickCP2.Imu.getGyro(&gx, &gy, &gz);

        // Draw display every 3rd IMU read (~33fps)
        loopCount++;
        if (loopCount >= 3) {
            loopCount = 0;
            canvas.fillSprite(COL_BG);
            drawStatusBar();
            drawIMUData(ax, ay, az, gx, gy, gz);
            drawRecBar();
            canvas.pushSprite(0, 0);
        }

        // Buffer IMU reading for batched BLE send
        batchBuffer[batchIndex].timestamp = now;
        batchBuffer[batchIndex].ax = (int16_t)(ax * 1000);
        batchBuffer[batchIndex].ay = (int16_t)(ay * 1000);
        batchBuffer[batchIndex].az = (int16_t)(az * 1000);
        batchBuffer[batchIndex].gx = (int16_t)(gx * 10);
        batchBuffer[batchIndex].gy = (int16_t)(gy * 10);
        batchBuffer[batchIndex].gz = (int16_t)(gz * 10);
        batchIndex++;

        // Send batch when full (3 readings per BLE notification)
        if (batchIndex >= BATCH_SIZE && deviceConnected) {
            uint8_t packet[4 + BATCH_SIZE * sizeof(IMUReading)];
            packet[0] = recording ? 1 : 0;
            packet[1] = (uint8_t)setNumber;
            packet[2] = BATCH_SIZE;
            packet[3] = 0;
            memcpy(&packet[4], batchBuffer, BATCH_SIZE * sizeof(IMUReading));
            pCharacteristic->setValue(packet, sizeof(packet));
            pCharacteristic->notify();
            batchIndex = 0;
        } else if (batchIndex >= BATCH_SIZE) {
            batchIndex = 0;
        }
    }
}