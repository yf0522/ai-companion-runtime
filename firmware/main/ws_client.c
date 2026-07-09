#include "ws_client.h"
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

static void ws_event_handler(void *arg, esp_event_base_t base, int32_t event_id, void *data) {
    esp_websocket_event_data_t *ws_data = (esp_websocket_event_data_t *)data;

    switch (event_id) {
    case WEBSOCKET_EVENT_CONNECTED:
        ESP_LOGI(TAG, "WebSocket connected, sending auth");
        connected = true;
        // Send first-message auth
        cJSON *auth = cJSON_CreateObject();
        cJSON_AddStringToObject(auth, "type", "auth");
        cJSON_AddStringToObject(auth, "token", WS_AUTH_TOKEN);
        char *auth_str = cJSON_PrintUnformatted(auth);
        esp_websocket_client_send_text(client, auth_str, strlen(auth_str), portMAX_DELAY);
        free(auth_str);
        cJSON_Delete(auth);
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
