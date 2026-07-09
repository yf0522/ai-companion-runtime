#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "nvs_flash.h"
#include "cJSON.h"

#include "config.h"
#include "state_machine.h"
#include "audio_pipeline.h"
#include "ws_client.h"
#include "local_reminder.h"

static const char *TAG = "main";
static bool audio_turn_active = false;

static void wifi_init(void);
static void on_ws_text(const char *data, int len);
static void on_ws_binary(const uint8_t *data, int len);
static void main_loop_task(void *arg);
static void reminder_check_task(void *arg);
static void send_audio_start(void);
static void send_audio_end(void);
static void send_command_receipt(cJSON *root, const char *receipt_type);
static void handle_reminder_create(cJSON *root);
static void begin_listen_turn(void);

void app_main(void) {
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    state_machine_init();
    audio_pipeline_init();
    local_reminder_init();
    wifi_init();
    ws_client_init(on_ws_text, on_ws_binary);

    ESP_LOGI(TAG, "Elder Companion device started");
    ESP_LOGI(TAG, "Protocol: audio_start/audio_end + JSON events from /ws/device/realtime");
    ESP_LOGI(TAG, "Say '%s' to wake me up", WAKE_WORD);

    xTaskCreate(main_loop_task, "main_loop", 8192, NULL, 5, NULL);
    xTaskCreate(reminder_check_task, "reminder_check", 4096, NULL, 3, NULL);
}

static void begin_listen_turn(void) {
    if (!audio_pipeline_is_ready()) {
        ESP_LOGE(TAG, "Cannot start listen turn: audio pipeline is not ready");
        state_machine_set(STATE_STANDBY);
        return;
    }
    if (!ws_client_is_connected()) {
        ws_client_connect();
    }
    audio_pipeline_start();
    state_machine_set(STATE_LISTENING);
    state_machine_reset_timeout();
    send_audio_start();
    audio_turn_active = true;
    ESP_LOGI(TAG, "listen turn started -> audio_start");
}

static void send_audio_start(void) {
    cJSON *msg = cJSON_CreateObject();
    cJSON_AddStringToObject(msg, "type", "audio_start");
    cJSON_AddNumberToObject(msg, "sample_rate", SAMPLE_RATE);
    ws_client_send_json_with_seq(msg);
    cJSON_Delete(msg);
}

static void send_audio_end(void) {
    cJSON *msg = cJSON_CreateObject();
    cJSON_AddStringToObject(msg, "type", "audio_end");
    ws_client_send_json_with_seq(msg);
    cJSON_Delete(msg);
}

static void main_loop_task(void *arg) {
    int16_t audio_buf[FRAME_SIZE_SAMPLES];

    while (1) {
        device_state_t state = state_machine_get();

        switch (state) {
        case STATE_STANDBY:
            // Production: WakeNet callback should call begin_listen_turn().
            // Host/protocol harness can force LISTENING via state_machine_set.
            vTaskDelay(pdMS_TO_TICKS(100));
            break;

        case STATE_LISTENING:
            if (state_machine_check_timeout()) {
                ESP_LOGI(TAG, "Standby timeout, going to sleep");
                if (audio_turn_active) {
                    send_audio_end();
                    audio_turn_active = false;
                }
                ws_client_disconnect();
                audio_pipeline_stop();
                state_machine_set(STATE_STANDBY);
                break;
            }

            if (!audio_turn_active) {
                begin_listen_turn();
            }

            int samples_read = audio_pipeline_read(audio_buf, FRAME_SIZE_SAMPLES);
            if (samples_read <= 0) {
                ESP_LOGE(TAG, "Audio capture failed; ending the current turn");
                send_audio_end();
                audio_turn_active = false;
                audio_pipeline_stop();
                state_machine_set(STATE_STANDBY);
                break;
            }
            ws_client_send_binary((uint8_t *)audio_buf, samples_read * sizeof(int16_t));

            if (audio_pipeline_vad_detected()) {
                send_audio_end();
                audio_turn_active = false;
                state_machine_set(STATE_PROCESSING);
                ESP_LOGI(TAG, "VAD end -> audio_end, waiting for server");
            }
            break;

        case STATE_PROCESSING:
            vTaskDelay(pdMS_TO_TICKS(50));
            break;

        case STATE_SPEAKING:
            // Stay in SPEAKING until tts_done (handled in on_ws_text).
            vTaskDelay(pdMS_TO_TICKS(20));
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

static void handle_reminder_create(cJSON *root) {
    cJSON *id = cJSON_GetObjectItem(root, "reminder_id");
    cJSON *label = cJSON_GetObjectItem(root, "label");
    cJSON *timer_type = cJSON_GetObjectItem(root, "timer_type");
    cJSON *repeat_mode = cJSON_GetObjectItem(root, "repeat_mode");
    cJSON *hour = cJSON_GetObjectItem(root, "hour");
    cJSON *minute = cJSON_GetObjectItem(root, "minute");
    cJSON *duration = cJSON_GetObjectItem(root, "duration_sec");

    local_reminder_add_structured(
        cJSON_IsString(id) ? id->valuestring : NULL,
        cJSON_IsString(label) ? label->valuestring : "reminder",
        cJSON_IsString(timer_type) ? timer_type->valuestring : "alarm",
        cJSON_IsString(repeat_mode) ? repeat_mode->valuestring : "once",
        cJSON_IsNumber(hour) ? hour->valueint : 0,
        cJSON_IsNumber(minute) ? minute->valueint : 0,
        cJSON_IsNumber(duration) ? duration->valueint : 0
    );
}

static void send_command_receipt(cJSON *root, const char *receipt_type) {
    cJSON *command_id = cJSON_GetObjectItem(root, "command_id");
    if (!cJSON_IsString(command_id)) {
        ESP_LOGW(TAG, "receipt skipped: command_id missing for %s", receipt_type);
        return;
    }
    cJSON *msg = cJSON_CreateObject();
    cJSON_AddStringToObject(msg, "type", "receipt");
    cJSON_AddStringToObject(msg, "command_id", command_id->valuestring);
    cJSON_AddStringToObject(msg, "receipt_type", receipt_type);
    cJSON *meta = cJSON_CreateObject();
    cJSON_AddStringToObject(meta, "firmware_version", FIRMWARE_VERSION);
    cJSON_AddStringToObject(meta, "state", "handled");
    cJSON_AddItemToObject(msg, "metadata", meta);
    ws_client_send_json_with_seq(msg);
    cJSON_Delete(msg);
}

static void on_ws_text(const char *data, int len) {
    ESP_LOGI(TAG, "WS text: %.*s", len, data);
    state_machine_reset_timeout();

    cJSON *root = cJSON_ParseWithLength(data, len);
    if (!root) {
        ESP_LOGW(TAG, "Invalid JSON from server");
        return;
    }

    cJSON *type = cJSON_GetObjectItem(root, "type");
    if (!cJSON_IsString(type)) {
        cJSON_Delete(root);
        return;
    }

    const char *t = type->valuestring;
    if (strcmp(t, "connected") == 0) {
        ESP_LOGI(TAG, "server connected");
    } else if (strcmp(t, "listening") == 0) {
        ESP_LOGI(TAG, "server listening");
    } else if (strcmp(t, "trace") == 0) {
        cJSON *tid = cJSON_GetObjectItem(root, "trace_id");
        ESP_LOGI(TAG, "trace_id=%s", cJSON_IsString(tid) ? tid->valuestring : "");
    } else if (strcmp(t, "asr_partial") == 0 || strcmp(t, "asr_final") == 0) {
        cJSON *text = cJSON_GetObjectItem(root, "text");
        ESP_LOGI(TAG, "%s: %s", t, cJSON_IsString(text) ? text->valuestring : "");
    } else if (strcmp(t, "risk_alert") == 0) {
        cJSON *level = cJSON_GetObjectItem(root, "level");
        ESP_LOGW(TAG, "risk_alert level=%s", cJSON_IsString(level) ? level->valuestring : "");
        state_machine_set(STATE_SPEAKING);
    } else if (strcmp(t, "first_reply") == 0 || strcmp(t, "delta") == 0) {
        // Text is informational; spoken audio arrives as binary PCM frames.
        state_machine_set(STATE_SPEAKING);
    } else if (strcmp(t, "reminder_create") == 0) {
        handle_reminder_create(root);
        send_command_receipt(root, "received");
    } else if (strcmp(t, "tool_status") == 0 || strcmp(t, "tool_result") == 0) {
        ESP_LOGI(TAG, "tool event: %s", t);
    } else if (strcmp(t, "final") == 0) {
        ESP_LOGI(TAG, "final received");
        send_command_receipt(root, "received");
    } else if (strcmp(t, "tts_done") == 0) {
        ESP_LOGI(TAG, "tts_done -> return to listening");
        send_command_receipt(root, "played");
        state_machine_set(STATE_LISTENING);
        state_machine_reset_timeout();
        audio_turn_active = false;
    } else if (strcmp(t, "no_speech") == 0) {
        ESP_LOGI(TAG, "no_speech -> listen again");
        state_machine_set(STATE_LISTENING);
        audio_turn_active = false;
    } else if (strcmp(t, "error") == 0) {
        cJSON *code = cJSON_GetObjectItem(root, "code");
        ESP_LOGE(TAG, "server error: %s", cJSON_IsString(code) ? code->valuestring : "unknown");
        state_machine_set(STATE_LISTENING);
        audio_turn_active = false;
    } else {
        ESP_LOGW(TAG, "unhandled type: %s", t);
    }

    cJSON_Delete(root);
}

static void on_ws_binary(const uint8_t *data, int len) {
    audio_pipeline_play(data, len);
    state_machine_set(STATE_SPEAKING);
}

static void wifi_init(void) {
#if CONFIG_COMPANION_ENABLE_WIFI
    ESP_LOGI(TAG, "Connecting to WiFi: %s", WIFI_SSID);
    // Standard ESP-IDF WiFi STA bring-up lives behind this flag.
    // Without board audio support, playback remains disabled and health reports not ready.
#else
    ESP_LOGW(TAG, "WiFi bring-up gated (CONFIG_COMPANION_ENABLE_WIFI=0); protocol code still active");
#endif
}
