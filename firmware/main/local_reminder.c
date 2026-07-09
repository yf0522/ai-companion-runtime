#include "local_reminder.h"
#include "config.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "nvs.h"
#include <string.h>
#include <time.h>

static const char *TAG = "local_reminder";
static local_reminder_t reminders[MAX_LOCAL_REMINDERS];
static int reminder_count = 0;

static void save_to_nvs(void) {
    nvs_handle_t handle;
    if (nvs_open("reminders", NVS_READWRITE, &handle) == ESP_OK) {
        nvs_set_blob(handle, "data", reminders, sizeof(reminders));
        nvs_set_i32(handle, "count", reminder_count);
        nvs_commit(handle);
        nvs_close(handle);
    }
}

static void load_from_nvs(void) {
    nvs_handle_t handle;
    if (nvs_open("reminders", NVS_READONLY, &handle) == ESP_OK) {
        size_t size = sizeof(reminders);
        nvs_get_blob(handle, "data", reminders, &size);
        int32_t count = 0;
        nvs_get_i32(handle, "count", &count);
        reminder_count = (int)count;
        nvs_close(handle);
        ESP_LOGI(TAG, "Loaded %d reminders from NVS", reminder_count);
    }
}

void local_reminder_init(void) {
    memset(reminders, 0, sizeof(reminders));
    reminder_count = 0;
    load_from_nvs();
}

void local_reminder_add(uint8_t hour, uint8_t minute, const char *title) {
    local_reminder_add_structured(NULL, title, "alarm", "once", hour, minute, 0);
}

void local_reminder_add_structured(
    const char *reminder_id,
    const char *title,
    const char *timer_type,
    const char *repeat_mode,
    int hour,
    int minute,
    int duration_sec
) {
    if (reminder_count >= MAX_LOCAL_REMINDERS) {
        ESP_LOGW(TAG, "Reminder list full");
        return;
    }

    local_reminder_t *r = &reminders[reminder_count++];
    memset(r, 0, sizeof(*r));
    r->active = 1;
    if (reminder_id) {
        strncpy(r->reminder_id, reminder_id, REMINDER_ID_LEN - 1);
    }
    if (title) {
        strncpy(r->title, title, REMINDER_TITLE_LEN - 1);
    }

    if (timer_type && strcmp(timer_type, "countdown") == 0) {
        r->kind = REMINDER_KIND_COUNTDOWN;
        r->duration_sec = duration_sec > 0 ? (uint32_t)duration_sec : 0;
        r->fire_at_epoch = (uint32_t)time(NULL) + r->duration_sec;
    } else if (repeat_mode && strcmp(repeat_mode, "daily") == 0) {
        r->kind = REMINDER_KIND_DAILY;
        r->hour = (uint8_t)hour;
        r->minute = (uint8_t)minute;
    } else {
        r->kind = REMINDER_KIND_ALARM;
        r->hour = (uint8_t)hour;
        r->minute = (uint8_t)minute;
    }

    save_to_nvs();
    ESP_LOGI(
        TAG,
        "Added reminder id=%s kind=%d %02d:%02d dur=%u title=%s",
        r->reminder_id,
        (int)r->kind,
        r->hour,
        r->minute,
        (unsigned)r->duration_sec,
        r->title
    );
}

void local_reminder_remove(int index) {
    if (index < 0 || index >= reminder_count) return;
    for (int i = index; i < reminder_count - 1; i++) {
        reminders[i] = reminders[i + 1];
    }
    reminder_count--;
    save_to_nvs();
}

void local_reminder_check(void) {
    time_t now;
    struct tm timeinfo;
    time(&now);
    localtime_r(&now, &timeinfo);

    for (int i = 0; i < reminder_count; i++) {
        if (!reminders[i].active) continue;

        if (reminders[i].kind == REMINDER_KIND_COUNTDOWN) {
            if (reminders[i].fire_at_epoch > 0 &&
                (uint32_t)now >= reminders[i].fire_at_epoch) {
                ESP_LOGI(TAG, "REMINDER FIRE id=%s: %s", reminders[i].reminder_id, reminders[i].title);
                reminders[i].active = 0;
                save_to_nvs();
            }
            continue;
        }

        if (reminders[i].hour == timeinfo.tm_hour &&
            reminders[i].minute == timeinfo.tm_min) {
            ESP_LOGI(TAG, "REMINDER FIRE id=%s: %s", reminders[i].reminder_id, reminders[i].title);
            if (reminders[i].kind == REMINDER_KIND_ALARM) {
                reminders[i].active = 0;
                save_to_nvs();
            }
        }
    }
}

int local_reminder_count(void) {
    return reminder_count;
}
