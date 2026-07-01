#!/usr/bin/env bash
# Speedrun LSAT: boot the Android emulator and open AnkiDroid in one step.
#
# Usage (from the anki-clone folder):
#   ./speedrun/scripts/phone.sh
#
# A phone-shaped window will appear on your Mac. If it's already running, this
# just brings AnkiDroid to the front.

set -euo pipefail

SDK="/opt/homebrew/share/android-commandlinetools"
ADB="$SDK/platform-tools/adb"
EMU="$SDK/emulator/emulator"
AVD="anki_lsat"
PKG="com.ichi2.anki.debug"

if [ ! -x "$ADB" ] || [ ! -x "$EMU" ]; then
  echo "Android tools not found under $SDK"
  echo "Install with: brew install --cask android-commandlinetools"
  exit 1
fi

# 1. Start the emulator only if one isn't already running.
if ! "$ADB" devices | grep -q "emulator-"; then
  echo "Starting the emulator ($AVD) — a phone window will open shortly..."
  "$EMU" -avd "$AVD" -netdelay none -netspeed full >/tmp/anki-emulator.log 2>&1 &
  echo "Waiting for Android to finish booting..."
  "$ADB" wait-for-device
  until [ "$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do
    sleep 2
  done
else
  echo "Emulator already running."
fi

# 2. Open AnkiDroid (its launcher activity).
"$ADB" shell am start -a android.intent.action.MAIN \
  -c android.intent.category.LAUNCHER \
  -n "$PKG/com.ichi2.anki.IntentHandler" >/dev/null

echo "Done — AnkiDroid is open on the emulator. Look for the phone window on your Mac."
echo "(If you don't see it: press F3 / Mission Control, or Cmd+Tab.)"
