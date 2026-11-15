#!/usr/bin/env bash
# Lock the camera's automatic controls. Usage: bash tools/camera_lock.sh [/dev/videoN] [focus]
# (The Python code does the same thing by itself; this is for manual checks.)
DEV=${1:-$(ls /dev/v4l/by-id/usb-*video-index0 2>/dev/null | head -1)}
FOCUS=${2:-200}
if [ -z "$DEV" ]; then echo "camera not found (is it on the powered hub?)"; exit 1; fi
echo "Using $DEV"
set_ctrl() { for name in "${@:2}"; do v4l2-ctl -d "$DEV" -c "$name=$1" 2>/dev/null && return 0; done; echo "  (could not set ${*:2})"; }
set_ctrl 0 focus_automatic_continuous focus_auto
set_ctrl "$FOCUS" focus_absolute
set_ctrl 1 auto_exposure exposure_auto
set_ctrl 0 exposure_dynamic_framerate exposure_auto_priority
set_ctrl 100 exposure_time_absolute exposure_absolute
set_ctrl 0 gain
set_ctrl 0 white_balance_automatic white_balance_temperature_auto
set_ctrl 4500 white_balance_temperature
set_ctrl 1 power_line_frequency
set_ctrl 0 sharpness
set_ctrl 0 led1_mode led_mode led light led_brightness illumination torch
v4l2-ctl -d "$DEV" --list-ctrls
