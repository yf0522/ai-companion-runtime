#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "nvs_flash.h"

#include "config.h"
#include "state_machine.h"
#include "audio_pipeline.h"
#include "ws_client.h"
#include "local_reminder.h"

static const char *TAG = "main";

// Forward declarations
static void wifi_init(void);
static void on_ws_text(const char *data, int len);
static void on_ws_binary(const uint8_t *data, int len);
static void main_loop_task(void *arg);
static void reminder_check_task(void *arg);

void app_main(void) {
    // Initialize NVS
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    // Initialize subsystems
    state_machine_init();
    audio_pipeline_init();
    local_reminder_init();
    wifi_init();
    ws_client_init(on_ws_text, on_ws_binary);

    ESP_LOGI(TAG, "Elder Companion device started");
    ESP_LOGI(TAG, "Say '%s' to wake me up", WAKE_WORD);

    // Start main loop
    xTaskCreate(main_loop_task, "main_loop", 8192, NULL, 5, NULL);
    xTaskCreate(reminder_check_task, "reminder_check", 4096, NULL, 3, NULL);
}

static void main_loop_task(void *arg) {
    int16_t audio_buf[FRAME_SIZE_SAMPLES];

    while (1) {
        device_state_t state = state_machine_get();

        switch (state) {
        case STATE_STANDBY:
            // Only wake word detection runs here
            // ESP-SR WakeNet processes audio in background
            // When wake word detected, transition to LISTENING
            // (In production: register wakenet callback that calls state_machine_set)
            vTaskDelay(pdMS_TO_TICKS(100));
            break;

        case STATE_LISTENING:
            // Check standby timeout
            if (state_machine_check_timeout()) {
                ESP_LOGI(TAG, "Standby timeout, going to sleep");
                ws_client_disconnect();
                audio_pipeline_stop();
                state_machine_set(STATE_STANDBY);
                break;
            }

            // Read processed audio (after AEC + NS)
            audio_pipeline_read(audio_buf, FRAME_SIZE_SAMPLES);

            // If VAD detected speech end, send to server
            if (audio_pipeline_vad_detected()) {
                state_machine_set(STATE_PROCESSING);
                // Send audio via WebSocket
                ws_client_send_binary((uint8_t *)audio_buf,
                                     FRAME_SIZE_SAMPLES * sizeof(int16_t));
            }
            break;

        case STATE_PROCESSING:
            // Waiting for server response
            // Handled by ws_client callbacks
            vTaskDelay(pdMS_TO_TICKS(50));
            break;

        case STATE_SPEAKING:
            // Audio playback handled by audio_pipeline_play()
            // When done, return to LISTENING
            state_machine_set(STATE_LISTENING);
            state_machine_reset_timeout();
            break;
        }

        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

static void reminder_check_task(void *arg) {
    while (1) {
        local_reminder_check();
        vTaskDelay(pdMS_TO_TICKS(REMINDER_CHECK_INTERVAL_S * 1000));
    }
}

static void on_ws_text(const char *data, int len) {
    ESP_LOGI(TAG, "WS text: %.*s", len, data);
    state_machine_reset_timeout();

    // Parse JSON and handle message types:
    // "connected" -> log
    // "first_reply" / "delta" / "final" -> TTS and play
    // "reminder" -> play reminder audio
    // "error" -> log
}

static void on_ws_binary(const uint8_t *data, int len) {
    // Receive audio from server (TTS output)
    audio_pipeline_play(data, len);
    state_machine_set(STATE_SPEAKING);
}

static void wifi_init(void) {
    ESP_LOGI(TAG, "Connecting to WiFi: %s", WIFI_SSID);
    // Standard ESP-IDF WiFi initialization:
    // esp_netif_init() -> esp_event_loop_create_default()
    // -> esp_netif_create_default_wifi_sta() -> esp_wifi_init()
    // -> esp_wifi_set_config() -> esp_wifi_start() -> esp_wifi_connect()
}
