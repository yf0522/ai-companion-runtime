#pragma once

// WiFi — set via menuconfig or sdkconfig
#define WIFI_SSID           CONFIG_WIFI_SSID
#define WIFI_PASS           CONFIG_WIFI_PASS
#define WS_SERVER_URI       CONFIG_WS_SERVER_URI
#define WS_AUTH_TOKEN       CONFIG_WS_AUTH_TOKEN
#define DEVICE_ID           CONFIG_DEVICE_ID
#define FIRMWARE_VERSION    "0.4.0-protocol"

// Wake word
#define WAKE_WORD           "小伴小伴"

// Audio
#define SAMPLE_RATE         16000
#define FRAME_SIZE_MS       30
#define FRAME_SIZE_SAMPLES  (SAMPLE_RATE * FRAME_SIZE_MS / 1000)

// AEC / NS
#define AEC_FILTER_LENGTH   512
#define NS_MODE             3   // aggressive

// Timeouts
#define VAD_SILENCE_TIMEOUT_MS     300
#define STANDBY_TIMEOUT_S          300
#define REMINDER_CHECK_INTERVAL_S  60

// Hardware bring-up gates (protocol code compiles either way)
#ifndef CONFIG_COMPANION_ENABLE_WIFI
#define CONFIG_COMPANION_ENABLE_WIFI 0
#endif
#ifndef CONFIG_COMPANION_ENABLE_ADF_AUDIO
#define CONFIG_COMPANION_ENABLE_ADF_AUDIO 0
#endif
#ifndef CONFIG_COMPANION_REQUIRE_WSS
#define CONFIG_COMPANION_REQUIRE_WSS 1
#endif
