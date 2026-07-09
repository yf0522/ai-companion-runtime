#pragma once

#include <stdbool.h>
#include <stdint.h>

void audio_pipeline_init(void);
void audio_pipeline_start(void);
void audio_pipeline_stop(void);
int audio_pipeline_read(int16_t *buf, int samples);
void audio_pipeline_play(const uint8_t *data, int len);
bool audio_pipeline_vad_detected(void);
