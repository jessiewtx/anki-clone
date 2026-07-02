# Speedrun LSAT — Build & Run (Desktop + Phone)

Two apps, **one shared Anki Rust engine**. Exam: **LSAT** (scored 120–180).
Desktop = an Anki fork (this repo). Phone companion = AnkiDroid.

> Verified on macOS (Apple Silicon). Commands assume you're in the repo root
> unless noted.

---

## 0. Prerequisites (one-time)

```bash
# Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Build tools (Homebrew)
brew install ninja just

# For the phone build: JDK + Android command-line tools
brew install --cask temurin@17 android-commandlinetools
```

Anki bootstraps its own Python (`uv`), Node, and protobuf during the build, so
you don't need to install those separately.

---

## 1. Desktop app (Anki fork)

### Build & run from source
```bash
just run          # builds pylib + qt and launches the desktop app
```

### Run the Rust engine change + its tests
Our engine change lives in `rslib/src/scheduler/skill_priority.rs`
(concept scheduler: rank by `weakness × exam weight`, retire solved problems,
discount speed-guesses) plus RPCs in `proto/anki/scheduler.proto`.

```bash
cargo test -p anki skill_priority                                  # 6 Rust unit tests
out/pyenv/bin/python speedrun/tests/test_skill_weakness_queue.py   # calls it from Python
out/pyenv/bin/python speedrun/tests/test_reorder_by_skill_weakness.py  # + undo-safety
```

### Build the installer (clean-machine .dmg)
```bash
./ninja installer:package
# → out/installer/dist/sharpe-26.05-mac-apple.dmg
```

### Install on a clean machine
Either build the `.dmg` (above) or **download the prebuilt one** — no dev toolchain
needed:
**https://github.com/jessiewtx/anki-clone/releases/tag/v26.05** → `sharpe-26.05-mac-apple.dmg`

1. Open the `.dmg` and drag **Sharpe** to `Applications`.
2. First launch (the app is **ad-hoc signed**, so macOS Gatekeeper warns once):
   - **right-click** `Sharpe.app` → **Open** → **Open**, or
   - `xattr -dr com.apple.quarantine /Applications/Sharpe.app`

> Ad-hoc signing means no `$99/yr` Apple certificate is required; the trade-off
> is the one-time Gatekeeper step above. Full notarization is a later/bonus item.

---

## 2. Phone companion (AnkiDroid on an Android emulator)

AnkiDroid repo: `../Anki-Android` (sibling of this repo).

### One-time: install an emulator image + create the AVD
```bash
SDK=/opt/homebrew/share/android-commandlinetools
"$SDK/cmdline-tools/latest/bin/sdkmanager" \
  "platform-tools" "emulator" \
  "platforms;android-35" "system-images;android-35;google_apis;arm64-v8a"

"$SDK/cmdline-tools/latest/bin/avdmanager" create avd \
  -n anki_lsat -k "system-images;android-35;google_apis;arm64-v8a" -d pixel_7
```
(Graders can instead install **Android Studio** → *Device Manager* → create a
Pixel 7, API 35 virtual device named `anki_lsat`.)

### Build the AnkiDroid APK
```bash
cd ../Anki-Android
./gradlew assemblePlayDebug
# → AnkiDroid/build/outputs/apk/play/debug/AnkiDroid-play-arm64-v8a-debug.apk
```

### Launch the phone (one command)
From this repo:
```bash
./speedrun/scripts/phone.sh      # boots the emulator (if needed) and opens AnkiDroid
```

Or manually:
```bash
SDK=/opt/homebrew/share/android-commandlinetools
"$SDK/emulator/emulator" -avd anki_lsat &                 # boot the phone window
"$SDK/platform-tools/adb" install -r \
  ../Anki-Android/AnkiDroid/build/outputs/apk/play/debug/AnkiDroid-play-arm64-v8a-debug.apk
"$SDK/platform-tools/adb" shell am start -a android.intent.action.MAIN \
  -c android.intent.category.LAUNCHER -n com.ichi2.anki.debug/com.ichi2.anki.IntentHandler
```

### Load the LSAT deck onto the phone
The deck is shared via **Anki sync** (desktop → local sync server → phone). See
`speedrun/scripts/sync_upload.py` for the desktop-side push; on the phone, open
AnkiDroid → **Sync**. (The deck is built from `speedrun/decks/lsat_seed.json` via
`speedrun/scripts/build_deck.py` → `out/lsat_seed.apkg`.)

---

## 3. Where things live
- **Rust engine change:** `rslib/src/scheduler/skill_priority.rs` (+ `proto/anki/scheduler.proto`, `rslib/src/scheduler/service/mod.rs`)
- **LSAT deck source:** `speedrun/decks/lsat_seed.json` → `speedrun/scripts/build_deck.py`
- **Honest scores (memory / performance / readiness + range + give-up):** `speedrun/scripts/compute_scores.py`
- **Design docs:** `docs/speedrun/PRD.md`, `docs/speedrun/rust-change.md`, `docs/speedrun/flashcards.md`
