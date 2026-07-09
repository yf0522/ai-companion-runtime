#include "ws_client.h"
#include "audio_pipeline.h"
#include "config.h"
#include "esp_log.h"
#include "esp_websocket_client.h"
#include "cJSON.h"
#include <string.h>

static const char *TAG = "ws_client";
static esp_websocket_client_handle_t client = NULL;
static ws_text_cb_t text_callback = NULL;
static ws_binary_cb_t binary_callback = NULL;
static bool connected = false;
static uint32_t next_seq = 1;

static bool transport_config_is_secure(void) {
#if CONFIG_COMPANION_REQUIRE_WSS
    return strncmp(WS_SERVER_URI, "wss://", 6) == 0;
#else
    return strncmp(WS_SERVER_URI, "ws://", 5) == 0 || strncmp(WS_SERVER_URI, "wss://", 6) == 0;
#endif
}

static void send_auth(void) {
    cJSON *auth = cJSON_CreateObject();
    cJSON_AddStringToObject(auth, "type", "auth");
    cJSON_AddStringToObject(auth, "auth_type", "device");
    cJSON_AddStringToObject(auth, "device_id", DEVICE_ID);
    cJSON_AddStringToObject(auth, "credential", WS_AUTH_TOKEN);
    cJSON_AddStringToObject(auth, "firmware_version", FIRMWARE_VERSION);
    cJSON *caps = cJSON_CreateObject();
    cJSON_AddBoolToObject(caps, "audio", audio_pipeline_is_ready());
    cJSON_AddBoolToObject(caps, "receipts", true);
    cJSON_AddBoolToObject(caps, "health", true);
    cJSON_AddBoolToObject(caps, "ota", true);
    cJSON_AddItemToObject(auth, "capabilities", caps);
    char *auth_str = cJSON_PrintUnformatted(auth);
    if (auth_str) {
        esp_websocket_client_send_text(client, auth_str, strlen(auth_str), portMAX_DELAY);
        free(auth_str);
    }
    cJSON_Delete(auth);
}

static void ws_event_handler(void *arg, esp_event_base_t base, int32_t event_id, void *data) {
    esp_websocket_event_data_t *ws_data = (esp_websocket_event_data_t *)data;

    switch (event_id) {
    case WEBSOCKET_EVENT_CONNECTED:
        ESP_LOGI(TAG, "WebSocket connected, sending auth");
        connected = true;
        next_seq = 1;
        send_auth();
        ws_client_send_heartbeat();
        break;

    case WEBSOCKET_EVENT_DATA:
        if (ws_data->op_code == 0x01 && text_callback) {
            // Text frame
            text_callback((const char *)ws_data->data_ptr, ws_data->data_len);
        } else if (ws_data->op_code == 0x02 && binary_callback) {
            // Binary frame (audio)
            binary_callback((const uint8_t *)ws_data->data_ptr, ws_data->data_len);
        }
        break;

    case WEBSOCKET_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "WebSocket disconnected");
        connected = false;
        break;

    case WEBSOCKET_EVENT_ERROR:
        ESP_LOGE(TAG, "WebSocket error");
        break;
    }
}

void ws_client_init(ws_text_cb_t on_text, ws_binary_cb_t on_binary) {
    text_callback = on_text;
    binary_callback = on_binary;

    if (!transport_config_is_secure()) {
        ESP_LOGE(TAG, "Invalid device transport config: CONFIG_WS_SERVER_URI must use wss:// when CONFIG_COMPANION_REQUIRE_WSS=1");
        client = NULL;
        return;
    }

    esp_websocket_client_config_t config = {
        .uri = WS_SERVER_URI,
        .buffer_size = 4096,
    };
    client = esp_websocket_client_init(&config);
    esp_websocket_register_events(client, WEBSOCKET_EVENT_ANY, ws_event_handler, NULL);
}

void ws_client_connect(void) {
    if (client) {
        esp_websocket_client_start(client);
    }
}

void ws_client_disconnect(void) {
    if (client) {
        esp_websocket_client_stop(client);
        connected = false;
    }
}

bool ws_client_is_connected(void) {
    return connected;
}

void ws_client_send_binary(const uint8_t *data, int len) {
    if (connected && client) {
        esp_websocket_client_send_bin(client, (const char *)data, len, portMAX_DELAY);
    }
}

void ws_client_send_text(const char *text) {
    if (connected && client) {
        esp_websocket_client_send_text(client, text, strlen(text), portMAX_DELAY);
    }
}

void ws_client_send_json_with_seq(void *json) {
    cJSON *root = (cJSON *)json;
    if (!root) {
        return;
    }
    cJSON_AddNumberToObject(root, "seq", next_seq++);
    char *payload = cJSON_PrintUnformatted(root);
    if (payload) {
        ws_client_send_text(payload);
        free(payload);
    }
}

void ws_client_send_heartbeat(void) {
    cJSON *msg = cJSON_CreateObject();
    cJSON_AddStringToObject(msg, "type", "heartbeat");
    cJSON_AddStringToObject(msg, "firmware_version", FIRMWARE_VERSION);
    cJSON *health = cJSON_CreateObject();
    cJSON_AddBoolToObject(health, "wifi_connected", connected);
    cJSON_AddBoolToObject(health, "audio_pipeline_initialized", audio_pipeline_is_ready());
    cJSON_AddStringToObject(health, "ota_verification_state", "pending_evidence");
    cJSON_AddItemToObject(msg, "health", health);
    ws_client_send_json_with_seq(msg);
    cJSON_Delete(msg);
}
