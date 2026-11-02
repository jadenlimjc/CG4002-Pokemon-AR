#pragma once

#include <stdint.h>

#include "secrets.h"

// The ignored local profile is selected by its presence. Without it, these
// values preserve the existing NUS/stujump behaviour exactly.
#if defined(__has_include)
#  if __has_include("network_profile.local.h")
#    define CG4002_LOCAL_NETWORK_PROFILE 1
#  endif
#endif

#ifdef CG4002_LOCAL_NETWORK_PROFILE
#  include "network_profile.local.h"
#else
namespace NetworkProfile {

static constexpr char NAME[] = "campus";
static constexpr bool WIFI_ENTERPRISE = true;
static const char *const WIFI_SSID = ::WIFI_SSID;
static const char *const WIFI_PASSWORD = ::WIFI_PASSWORD;

static constexpr char JUMP_HOST[] = "stujump.comp.nus.edu.sg";
static constexpr uint16_t JUMP_PORT = 22;
static const char *const JUMP_USERNAME = ::SOC_USERNAME;
static const char *const JUMP_PASSWORD = ::SOC_PASSWORD;

// Resolved by the jump host.
static constexpr char TARGET_HOST[] = "makerslab-fpga-38.ddns.comp.nus.edu.sg";
static constexpr uint16_t TARGET_SSH_PORT = 22;
static constexpr char TARGET_USERNAME[] = "xilinx";
static constexpr char TARGET_PASSWORD[] = "xilinx";

// Resolved by the target after the second SSH login.
static constexpr char SERVICE_HOST[] = "localhost";
static constexpr uint16_t SERVICE_PORT = 1883;

} // namespace NetworkProfile
#endif

