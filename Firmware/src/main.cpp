#include <Arduino.h>
#include <SPI.h>
#include <TFT_eSPI.h>
#include <XPT2046_Touchscreen.h>

// --- BLE Libraries ---
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// PhysioNet array of ECG data
#include "ecg_data.h"

// --- TFT & Touch Pin Definitions for CYD (Shared SPI) ---
#define XPT2046_IRQ 36
#define XPT2046_MOSI 13  
#define XPT2046_MISO 12  
#define XPT2046_CLK 14   
#define XPT2046_CS 33

SPIClass mySpi = SPIClass(VSPI);
XPT2046_Touchscreen ts(XPT2046_CS, XPT2046_IRQ);
TFT_eSPI tft = TFT_eSPI();

uint8_t ads_payload[27];

// Definition of how much packets will be sent (e.g. 15 packets of 27 bytes) 
#define BATCH_SIZE 15
uint8_t batch_buffer[27 * BATCH_SIZE];
int batch_index = 0;

// --- BLE Variables ---
BLEServer* pServer = NULL;
BLECharacteristic* pCharacteristic = NULL;
bool deviceConnected = false;
bool oldDeviceConnected = false;

bool is_taking_screenshot = false;

// These UUIDs have to be the same in the device receiving the signal
#define SERVICE_UUID           "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
#define CHARACTERISTIC_UUID_TX "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"

// Callback for device disconnections
class MyServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
      deviceConnected = true;
    };

    void onDisconnect(BLEServer* pServer) {
      deviceConnected = false;
    }
};

// --- Simulation Variables ---
int current_bpm = 60;
int noise_amplitude_50hz = 0; // Starts clean
unsigned long global_time_ms = 0;

int output_mode = 0; // 0 = Only Bluetooth, 1 = Only USB, 2 = Both
int simulate_leadoff_ch = 0; // 0 = OK, 1 = CH1 OFF...

unsigned int QRSCount = 0, IdleCount = 0;
unsigned int qrs_cutoff = 543, idle_cutoff = 0;
#define QRS 1
#define IDLE 2
unsigned int State = QRS;

// Timer and Touch Debounce
hw_timer_t * timer = NULL;
unsigned long lastTouchTime = 0;

// =========================================================================
// FREERTOS VARIABLES (Dual-Core)
// =========================================================================
SemaphoreHandle_t timerSemaphore;
QueueHandle_t ecgQueue;

// =========================================================================
// TIMER INTERRUPT
// =========================================================================
void IRAM_ATTR onTimer() {
  BaseType_t xHigherPriorityTaskWoken = pdFALSE;
  // Shares the semaphore to the aquisition task to run immediately
  xSemaphoreGiveFromISR(timerSemaphore, &xHigherPriorityTaskWoken);
  if (xHigherPriorityTaskWoken) {
    portYIELD_FROM_ISR();
  }
}

// This function is made to screenshot the CYD TFT display
void dumpScreenshotSerial() {
  is_taking_screenshot = true; // Pauses the ECG delivery by Serial
  vTaskDelay(50 / portTICK_PERIOD_MS); // Delay for the last packet to be delivered

  uint16_t w = tft.width();
  uint16_t h = tft.height();
  uint32_t fileSize = 54 + (w * h * 3);
  
  // BMP header
  unsigned char bmpFileHeader[14] = {'B','M', 0,0,0,0, 0,0, 0,0, 54,0,0,0};
  unsigned char bmpInfoHeader[40] = {40,0,0,0, 0,0,0,0, 0,0,0,0, 1,0, 24,0};

  bmpFileHeader[2] = (unsigned char)(fileSize);
  bmpFileHeader[3] = (unsigned char)(fileSize >> 8);
  bmpFileHeader[4] = (unsigned char)(fileSize >> 16);
  bmpFileHeader[5] = (unsigned char)(fileSize >> 24);

  bmpInfoHeader[4] = (unsigned char)(w);
  bmpInfoHeader[5] = (unsigned char)(w >> 8);
  bmpInfoHeader[6] = (unsigned char)(w >> 16);
  bmpInfoHeader[7] = (unsigned char)(w >> 24);
  
  int32_t negHeight = -h; 
  bmpInfoHeader[8] = (unsigned char)(negHeight);
  bmpInfoHeader[9] = (unsigned char)(negHeight >> 8);
  bmpInfoHeader[10] = (unsigned char)(negHeight >> 16);
  bmpInfoHeader[11] = (unsigned char)(negHeight >> 24);

  // Signals to the serial the transmission is starting
  Serial.println("\n---START_BMP---");

  // Sends header by HEX
  for(int i=0; i<14; i++) Serial.printf("%02X", bmpFileHeader[i]);
  for(int i=0; i<40; i++) Serial.printf("%02X", bmpInfoHeader[i]);
  Serial.println(); // New line after header

  // Reads value of pixels and transmits via Serial
  for (int y = 0; y < h; y++) {
    for (int x = 0; x < w; x++) {
      uint16_t color = tft.readPixel(x, y);
      
      uint8_t r = (color & 0xF800) >> 8;
      uint8_t g = (color & 0x07E0) >> 3;
      uint8_t b = (color & 0x001F) << 3;

      Serial.printf("%02X%02X%02X", b, g, r);
    }
    Serial.println(); // Breaks line after each row
    vTaskDelay(1 / portTICK_PERIOD_MS); 
  }

  Serial.println("---END_BMP---");
  
  is_taking_screenshot = false; // Resume ECG transmission
}

void pack24Bit(int32_t value, int startIndex) {
  ads_payload[startIndex]     = (value >> 16) & 0xFF; 
  ads_payload[startIndex + 1] = (value >> 8)  & 0xFF; 
  ads_payload[startIndex + 2] = value & 0xFF;        
}

void updateBPM(int bpm) {
  int ms_per_beat = 60000 / bpm;
  if (ms_per_beat >= NUM_SAMPLES) {
    qrs_cutoff = NUM_SAMPLES;
    idle_cutoff = ms_per_beat - NUM_SAMPLES;
  } else {
    qrs_cutoff = ms_per_beat; 
    idle_cutoff = 0;
  }
}

// --- UI Drawing Functions ---
void drawUI() {
  tft.fillScreen(TFT_BLACK);
  
  // Title
  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.drawCentreString("ADS1298 SIMULATOR", 160, 10, 4);

  // BPM Controls
  tft.fillRoundRect(20, 60, 80, 60, 5, TFT_DARKGREY);  // BPM -
  tft.drawCentreString("-", 60, 75, 4);
  tft.fillRoundRect(220, 60, 80, 60, 5, TFT_DARKGREY); // BPM +
  tft.drawCentreString("+", 260, 75, 4);
  
  // Noise Controls
  tft.fillRoundRect(20, 150, 80, 60, 5, TFT_DARKGREY);  // Noise -
  tft.drawCentreString("-", 60, 165, 4);
  tft.fillRoundRect(220, 150, 80, 60, 5, TFT_DARKGREY); // Noise +
  tft.drawCentreString("+", 260, 165, 4);

  // Botão de Saída (Output)
  tft.fillRoundRect(100, 205, 120, 30, 5, TFT_BLUE);
  
  // Botão de Lead-Off Inicial (Fundo verde indica OK)
  tft.fillRoundRect(10, 205, 80, 30, 5, TFT_DARKGREEN);
}

void updateDisplayValues() {
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  
  // Update BPM Text
  tft.drawCentreString("BPM", 160, 65, 2);
  char bpmStr[10];
  sprintf(bpmStr, "%03d", current_bpm);
  tft.drawCentreString(bpmStr, 160, 85, 4);

  // Update Noise Text
  tft.drawCentreString("50Hz Noise", 160, 155, 2);
  char noiseStr[10];
  if (noise_amplitude_50hz == 0) sprintf(noiseStr, "OFF  ");
  else sprintf(noiseStr, "%dk ", noise_amplitude_50hz / 1000);
  tft.drawCentreString(noiseStr, 160, 175, 4);

  // Update Output Mode Text
  tft.setTextColor(TFT_WHITE, TFT_BLUE); 
  if (output_mode == 0)      tft.drawCentreString("SAIDA: BLE", 160, 212, 2);
  else if (output_mode == 1) tft.drawCentreString("SAIDA: USB", 160, 212, 2);
  else if (output_mode == 2) tft.drawCentreString("SAIDA: USB+BLE", 160, 212, 2);

  // NOVO: Update Lead-Off Text e Cor do Botão
  if (simulate_leadoff_ch == 0) {
    tft.fillRoundRect(10, 205, 80, 30, 5, TFT_DARKGREEN);
    tft.setTextColor(TFT_WHITE, TFT_DARKGREEN);
    tft.drawCentreString("LEAD: OK", 50, 212, 2);
  } else {
    tft.fillRoundRect(10, 205, 80, 30, 5, TFT_RED);
    tft.setTextColor(TFT_WHITE, TFT_RED);
    char loffStr[10];
    sprintf(loffStr, "LEAD: CH%d", simulate_leadoff_ch);
    tft.drawCentreString(loffStr, 50, 212, 2);
  }
}

// =========================================================================
// TASK 1: Signal Aquision (CORE 1 - Priority 2)
// =========================================================================
void ecgAcquisitionTask(void *pvParameters) {
  unsigned long max_time_ecg = 0;
  unsigned long last_print_time = millis();

  for(;;) {
    // Sleeps until timer frees the semaphore, each 1 ms
    if (xSemaphoreTake(timerSemaphore, portMAX_DELAY) == pdTRUE) {
      unsigned long t_start = micros(); 
      global_time_ms++;

      // Variables to store the Flash readings
      int32_t val_I  = 0, val_II = 0, val_V1 = 0, val_V2 = 0;
      int32_t val_V3 = 0, val_V4 = 0, val_V5 = 0, val_V6 = 0;

      if (State == QRS) {
        const float SIMULATOR_GAIN = 20.97;
        val_I  = (int16_t)pgm_read_word(&ecg_lead_i[QRSCount]) * SIMULATOR_GAIN;
        val_II = (int16_t)pgm_read_word(&ecg_lead_ii[QRSCount]) * SIMULATOR_GAIN;
        val_V1 = (int16_t)pgm_read_word(&ecg_lead_v1[QRSCount]) * SIMULATOR_GAIN;
        val_V2 = (int16_t)pgm_read_word(&ecg_lead_v2[QRSCount]) * SIMULATOR_GAIN;
        val_V3 = (int16_t)pgm_read_word(&ecg_lead_v3[QRSCount]) * SIMULATOR_GAIN;
        val_V4 = (int16_t)pgm_read_word(&ecg_lead_v4[QRSCount]) * SIMULATOR_GAIN;
        val_V5 = (int16_t)pgm_read_word(&ecg_lead_v5[QRSCount]) * SIMULATOR_GAIN;
        val_V6 = (int16_t)pgm_read_word(&ecg_lead_v6[QRSCount]) * SIMULATOR_GAIN;

        QRSCount++;
        if (QRSCount >= NUM_SAMPLES) {
          QRSCount = 0;
          State = (idle_cutoff > 0) ? IDLE : QRS;
        }
      } 
      else if (State == IDLE) {
        IdleCount++;
        if (IdleCount >= idle_cutoff) {
          IdleCount = 0;
          State = QRS;
        }
      }

      int32_t noise_50hz = 0;
      if (noise_amplitude_50hz > 0) {
        float phase = (global_time_ms % 20) / 20.0;
        noise_50hz = (int32_t)(sin(2.0 * PI * phase) * noise_amplitude_50hz);
      }

      ads_payload[0] = 0xC0;
      ads_payload[1] = 0x00;
      ads_payload[2] = 0x00;

      if (simulate_leadoff_ch > 0) {
        if (simulate_leadoff_ch >= 1 && simulate_leadoff_ch <= 4) {
          ads_payload[1] = (1 << (simulate_leadoff_ch - 1 + 4)); 
        } 
        else if (simulate_leadoff_ch >= 5 && simulate_leadoff_ch <= 8) {
          ads_payload[0] = 0xC0 | (1 << (simulate_leadoff_ch - 5)); 
        }
      }

      int32_t ch1_I  = val_I  + noise_50hz;                  
      int32_t ch2_II = val_II + noise_50hz;          
      int32_t ch3_V1 = val_V1 + noise_50hz;        
      int32_t ch4_V2 = val_V2 + noise_50hz;        
      int32_t ch5_V3 = val_V3 + noise_50hz;          
      int32_t ch6_V4 = val_V4 + noise_50hz;          
      int32_t ch7_V5 = val_V5 + noise_50hz;                  
      int32_t ch8_V6 = val_V6 + noise_50hz;          

      int32_t saturated_value = 8388607; 
      
      if (simulate_leadoff_ch == 1) ch1_I = saturated_value;
      else if (simulate_leadoff_ch == 2) ch2_II = saturated_value;
      else if (simulate_leadoff_ch == 3) ch3_V1 = saturated_value;
      else if (simulate_leadoff_ch == 4) ch4_V2 = saturated_value;
      else if (simulate_leadoff_ch == 5) ch5_V3 = saturated_value;
      else if (simulate_leadoff_ch == 6) ch6_V4 = saturated_value;
      else if (simulate_leadoff_ch == 7) ch7_V5 = saturated_value;
      else if (simulate_leadoff_ch == 8) ch8_V6 = saturated_value;

      pack24Bit(ch1_I, 3);
      pack24Bit(ch2_II, 6);
      pack24Bit(ch3_V1, 9);
      pack24Bit(ch4_V2, 12);
      pack24Bit(ch5_V3, 15);
      pack24Bit(ch6_V4, 18);
      pack24Bit(ch7_V5, 21);
      pack24Bit(ch8_V6, 24);
      
      // Sends the 27 bytes packet to the queue
      xQueueSend(ecgQueue, ads_payload, 0);

      unsigned long t_end = micros();
      unsigned long tempo_gasto = t_end - t_start;
      if(tempo_gasto > max_time_ecg) max_time_ecg = tempo_gasto;
    }
  }
}

// =========================================================================
// TASK 2: Screen, Touch and Transmission (CORE 0 - Prioridade 1)
// =========================================================================
void uiAndCommsTask(void *pvParameters) {
  uint8_t received_payload[27];

  for(;;) {
    // --- 1. HANDLE TOUCH UI ---
    if (ts.touched() && (millis() - lastTouchTime > 300)) { 
      TS_Point p = ts.getPoint();
      
      int touch_x = map(p.y, 260, 3880, 0, 320); 
      int touch_y = map(p.x, 3830, 300, 240, 0); 

      bool ui_changed = false;

      if (touch_x > 20 && touch_x < 100 && touch_y > 60 && touch_y < 120) {
        if (current_bpm > 30) { current_bpm -= 5; ui_changed = true; }
      }
      else if (touch_x > 220 && touch_x < 300 && touch_y > 60 && touch_y < 120) {
        if (current_bpm < 200) { current_bpm += 5; ui_changed = true; }
      }
      else if (touch_x > 20 && touch_x < 100 && touch_y > 150 && touch_y < 210) {
        if (noise_amplitude_50hz > 0) { noise_amplitude_50hz -= 50000; ui_changed = true; }
      }
      else if (touch_x > 220 && touch_x < 300 && touch_y > 150 && touch_y < 210) {
        if (noise_amplitude_50hz < 500000) { noise_amplitude_50hz += 50000; ui_changed = true; }
      }
      else if (touch_x > 110 && touch_x < 240 && touch_y > 195) {
        output_mode++;
        if (output_mode > 2) output_mode = 0; 
        ui_changed = true;
      }
      else if (touch_x > 0 && touch_x < 100 && touch_y > 195) {
        simulate_leadoff_ch++;
        if (simulate_leadoff_ch > 8) simulate_leadoff_ch = 0; 
        ui_changed = true;
      }
      /* Screenshot via Serial is commented so it doesn't interfere with the transmission
      else if (touch_x > 270 && touch_x < 315 && touch_y > 5 && touch_y < 35) {
        dumpScreenshotSerial();
      } 
      */

      if (ui_changed) {
        updateBPM(current_bpm); 
        updateDisplayValues();  
      }
      
      lastTouchTime = millis();
    }

    // --- 2. BLE RECONNECTION LOGIC ---
    if (!deviceConnected && oldDeviceConnected) {
        vTaskDelay(500 / portTICK_PERIOD_MS); // Delay for the bluetooth stack to process
        pServer->startAdvertising(); // Resets advertising
        oldDeviceConnected = deviceConnected;
    }
    if (deviceConnected && !oldDeviceConnected) {
        oldDeviceConnected = deviceConnected;
    }

    // --- 3. FREE QUEUE AND SEND ---
    while(xQueueReceive(ecgQueue, received_payload, 0) == pdTRUE) {
      memcpy(&batch_buffer[batch_index * 27], received_payload, 27);
      batch_index++;

      if (batch_index >= BATCH_SIZE) {
        if (deviceConnected && (output_mode == 0 || output_mode == 2)) {
          pCharacteristic->setValue(batch_buffer, 27 * BATCH_SIZE); 
          pCharacteristic->notify(); 
          
          // Give the BLE PHY layer time to clear its buffer
          vTaskDelay(1 / portTICK_PERIOD_MS); 
        }
        
        if ((output_mode == 1 || output_mode == 2) && !is_taking_screenshot) {
          Serial.write(batch_buffer, 27 * BATCH_SIZE);
        } 
        batch_index = 0; 
      }
    }

    // Pass control back to the Core 0 to avoid Watchdog resets
    vTaskDelay(1 / portTICK_PERIOD_MS); 
  }
}

// =========================================================================
// SETUP
// =========================================================================
void setup() {
  Serial.begin(921600); 

  // --- BLE CONFIG ---
  BLEDevice::init("CYD_ADS1298_Sim"); 
  BLEDevice::setMTU(512);
  
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());

  BLEService *pService = pServer->createService(SERVICE_UUID);
  pCharacteristic = pService->createCharacteristic(
                      CHARACTERISTIC_UUID_TX,
                      BLECharacteristic::PROPERTY_NOTIFY
                    );
                    
  pCharacteristic->addDescriptor(new BLE2902());
  pService->start();

  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setScanResponse(true);
  pAdvertising->setMinPreferred(0x06);  
  pAdvertising->setMinPreferred(0x12);
  BLEDevice::startAdvertising();

  updateBPM(current_bpm); 

  tft.begin();
  tft.setRotation(1); // Landscape
  
  mySpi.begin(XPT2046_CLK, XPT2046_MISO, XPT2046_MOSI, XPT2046_CS);
  ts.begin(mySpi);
  ts.setRotation(1); 

  drawUI();
  updateDisplayValues();

  // --- FREERTOS INIT ---
  timerSemaphore = xSemaphoreCreateBinary();
  // Creates a queue to handle until 20 packets of 27 bytes (safety buffer)
  ecgQueue = xQueueCreate(20, 27 * sizeof(uint8_t)); 

  // Begin aquisition task on CORE 1 (High priority: 2)
  xTaskCreatePinnedToCore(ecgAcquisitionTask, "ECG_Task", 4096, NULL, 2, NULL, 1);
  
  // Begin Comms/UI task on CORE 0 (Normal priority: 1)
  xTaskCreatePinnedToCore(uiAndCommsTask, "UI_Task", 8192, NULL, 1, NULL, 0);

  // Begins physical timer at 1000 Hz
  timer = timerBegin(0, 80, true); 
  timerAttachInterrupt(timer, &onTimer, true);
  timerAlarmWrite(timer, 1000, true); 
  timerAlarmEnable(timer);
}

// =========================================================================
// LOOP
// =========================================================================
void loop() {
  // Destroy default Arduino's loop function, to let FreeRTOS handle
  vTaskDelete(NULL); 
}