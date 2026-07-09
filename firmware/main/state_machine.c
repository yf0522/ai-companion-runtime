#include "state_machine.h"
#include "config.h"
#include "esp_log.h"
#include "esp_timer.h"

static const char *TAG = "state_machine";
static device_state_t current_state = STATE_STANDBY;
static int64_t last_activity_us = 0;

void state_machine_init(void) {
    current_state = STATE_STANDBY;
    last_activity_us = esp_timer_get_time();
    ESP_LOGI(TAG, "State machine initialized: STANDBY");
}

device_state_t state_machine_get(void) {
    return current_state;
}

void state_machine_set(device_state_t new_state) {
    if (current_state != new_state) {
        ESP_LOGI(TAG, "State: %d -> %d", current_state, new_state);
        current_state = new_state;
        if (new_state != STATE_STANDBY) {
            state_machine_reset_timeout();
        }
    }
}

void state_machine_reset_timeout(void) {
    last_activity_us = esp_timer_get_time();
}

bool state_machine_check_timeout(void) {
    if (current_state == STATE_STANDBY) return false;
    int64_t elapsed_s = (esp_timer_get_time() - last_activity_us) / 1000000;
    return elapsed_s >= STANDBY_TIMEOUT_S;
}
