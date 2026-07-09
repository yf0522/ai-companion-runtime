#pragma once

#include <stdint.h>

#define MAX_LOCAL_REMINDERS 20
#define REMINDER_ID_LEN 48
#define REMINDER_TITLE_LEN 64

typedef enum {
    REMINDER_KIND_ALARM = 0,
    REMINDER_KIND_DAILY = 1,
    REMINDER_KIND_COUNTDOWN = 2,
} reminder_kind_t;

typedef struct {
    char reminder_id[REMINDER_ID_LEN];
    uint8_t hour;
    uint8_t minute;
    uint32_t duration_sec;
    uint32_t fire_at_epoch;  // for countdown; 0 = unused
    reminder_kind_t kind;
    char title[REMINDER_TITLE_LEN];
    uint8_t active;
} local_reminder_t;

void local_reminder_init(void);
void local_reminder_add(uint8_t hour, uint8_t minute, const char *title);
void local_reminder_add_structured(
    const char *reminder_id,
    const char *title,
    const char *timer_type,
    const char *repeat_mode,
    int hour,
    int minute,
    int duration_sec
);
void local_reminder_remove(int index);
void local_reminder_check(void);
int local_reminder_count(void);
