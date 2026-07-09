#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef void (*ws_text_cb_t)(const char *data, int len);
typedef void (*ws_binary_cb_t)(const uint8_t *data, int len);

void ws_client_init(ws_text_cb_t on_text, ws_binary_cb_t on_binary);
void ws_client_connect(void);
void ws_client_disconnect(void);
bool ws_client_is_connected(void);
void ws_client_send_binary(const uint8_t *data, int len);
void ws_client_send_text(const char *text);
void ws_client_send_json_with_seq(void *json);
void ws_client_send_heartbeat(void);
