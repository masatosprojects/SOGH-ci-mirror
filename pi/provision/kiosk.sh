#!/usr/bin/env bash
# Opens the local status page full-screen on the Pi monitor. Stop: Alt+F4, or  pkill -x chromium
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0
exec chromium --ozone-platform=wayland --kiosk --noerrdialogs --disable-infobars --lang=ja --accept-lang=ja --disable-features=Translate,TranslateUI,TranslateSubFrames --user-data-dir=/tmp/sogh-kiosk http://127.0.0.1:8765/
