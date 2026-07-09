#pragma once

#include <stdint.h>

#define MAX_LOCAL_REMINDERS 20

typedef struct {
    uint8_t hour;
    uint8_t minute;
    char title[64];
    uint8_t active;
} local_reminder_t;

void local_reminder_init(void);
void local_reminder_add(uint8_t hour, uint8_t minute, const char *title);
void local_reminder_remove(int index);
void local_reminder_check(void);  // Call every minute
int local_reminder_count(void);
