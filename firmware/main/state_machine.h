#pragma once

#include <stdbool.h>

typedef enum {
    STATE_STANDBY,
    STATE_LISTENING,
    STATE_PROCESSING,
    STATE_SPEAKING,
} device_state_t;

void state_machine_init(void);
device_state_t state_machine_get(void);
void state_machine_set(device_state_t new_state);
void state_machine_reset_timeout(void);
bool state_machine_check_timeout(void);
