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
    if (reminder_count >= MAX_LOCAL_REMINDERS) {
        ESP_LOGW(TAG, "Reminder list full");
        return;
    }
    local_reminder_t *r = &reminders[reminder_count++];
    r->hour = hour;
    r->minute = minute;
    r->active = 1;
    strncpy(r->title, title, sizeof(r->title) - 1);
    save_to_nvs();
    ESP_LOGI(TAG, "Added reminder: %02d:%02d %s", hour, minute, title);
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
        if (reminders[i].hour == timeinfo.tm_hour &&
            reminders[i].minute == timeinfo.tm_min) {
            ESP_LOGI(TAG, "REMINDER: %s", reminders[i].title);
            // In production: trigger speaker playback of reminder text
            // audio_pipeline_play_tts(reminders[i].title);
        }
    }
}

int local_reminder_count(void) {
    return reminder_count;
}
