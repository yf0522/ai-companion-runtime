#include "audio_pipeline.h"
#include "config.h"
#include "esp_log.h"

static const char *TAG = "audio_pipeline";

/*
 * NOTE: Full implementation requires ESP-ADF and ESP-SR components.
 * The pipeline structure:
 *   I2S Mic Reader -> AEC (ref: speaker output) -> NS -> VAD -> Raw Buffer
 *   Raw Buffer -> I2S Speaker Writer
 *
 * This file provides the interface. When building with ESP-ADF:
 * - Use audio_pipeline_create() / audio_pipeline_register()
 * - Use algorithm_stream for AEC + NS (algo_config.algo_mask = AEC | NS | VAD)
 * - Use i2s_stream for mic input and speaker output
 * - Use raw_stream for reading processed audio
 */

static bool vad_active = false;
static bool pipeline_ready = false;

void audio_pipeline_init(void) {
    ESP_LOGI(TAG, "Audio pipeline init (AEC filter=%d, NS mode=%d, SR=%d, adf=%d)",
             AEC_FILTER_LENGTH, NS_MODE, SAMPLE_RATE, CONFIG_COMPANION_ENABLE_ADF_AUDIO);
#if CONFIG_COMPANION_ENABLE_ADF_AUDIO
    ESP_LOGE(TAG, "ADF audio was enabled, but the production pipeline is not linked in this build");
#else
    ESP_LOGW(TAG, "Audio pipeline unavailable; capture and playback remain disabled");
#endif
}

bool audio_pipeline_is_ready(void) {
    return pipeline_ready;
}

void audio_pipeline_start(void) {
    ESP_LOGI(TAG, "Audio pipeline started");
    // audio_pipeline_run(pipeline);
}

void audio_pipeline_stop(void) {
    ESP_LOGI(TAG, "Audio pipeline stopped");
    // audio_pipeline_stop(pipeline); audio_pipeline_wait_for_stop(pipeline);
}

int audio_pipeline_read(int16_t *buf, int samples) {
    (void)buf;
    (void)samples;
    return 0;
}

void audio_pipeline_play(const uint8_t *data, int len) {
    (void)data;
    (void)len;
}

bool audio_pipeline_vad_detected(void) {
    return vad_active;
}
