# BREATHE Vision: complete build guide, from zero to demo

This guide takes you from "box of parts" to "3-minute demo for the judges", **using your printed BREATHE foundation** (the red/orange print in your photo, dimensions from `BREATHE_foundation_dimensions.pdf`). Follow it **in order**. Every step says **where** you are and **what to type or click**.

> **How to read the boxes**
> - 💻 **MAC terminal**: the **Terminal** app on your Mac. Open it with **command+space**, type `Terminal` and press **return** (or *Finder → Applications → Utilities → Terminal*).
> - 🟦 **BOARD terminal**: a terminal *on the UNO Q*, reached over SSH (Part 5). Its prompt looks like `arduino@breathe:~$`.
> - 🧩 **App Lab**: the Arduino App Lab app on your Mac.
> - 🌐 **Browser**: Chrome, Firefox, Edge or Safari.
>
> Type or paste (**command+V**) commands exactly as shown, one block at a time, and press **return** after each.
> **Keys:** in Terminal and on the board, shortcuts like **control+C** use the **control** key, not command.
> Replace anything in `<angle brackets>` (for example `<board-ip>`) with your own value, without the brackets.

**Time budget:** Parts 1–8 take about 1.5 h. Part 9 (camera test) is your "hour-1" check. Parts 10–11 (camera mounting and calibration) take about 1 h. Part 12 (database) takes 20 min.

---

## Part 0: What you are building

### 0.1 Your foundation, as the software sees it
From your drawing (top view, camera at the front, y = 0, centre line x = 90):

```
 y=153  ┌──────────── orange SCREEN 130 wide (x 25–155), 73.6 high ────────────┐   ← bright background
 y=118  │        battery holder 78.4 × 32.8, 4 dark cells, tops at z 45.6        │   ← what we measure
 y=112  ├──────────────────────── cross bar ───────────────────────────────────┤
        │  UNO Q cradle (x 3.6–73)           │ Knob / Thermo / Buzzer cradles │
 y=5–31 │              old camera stand 34×26 (x 73–107), can stay            │
        └────────────────────────────────────────────────────────────────────┘
 y≈−52                 ◉ Arduino USB Camera on its own base, lens z 49–51        ← cells' back edge at 20 cm
```

**What I took from your photo and drawing:**
* **Dark grey/black cells in front of an orange screen** already give strong contrast, so **no tape or extra lights are needed**. The software measures in the **red colour channel**, where the orange screen is brightest and the dark cells stay dark.
* **The screen's own left, right and top edges** are now the "did the camera move?" reference, so no stuck-on squares are needed.
* **The camera stand was designed for the C920.** The Arduino camera works best **on its own base, about 5 cm in front of the foundation**, on the centre line, lens 49–51 mm high (Part 10.2). That keeps the cells at its 20 cm focus distance. The software fits the camera's exact position, sideways offset and turn. It works with the lens above **or** below the cell tops; only z ≈ 44–47.7 mm (cell-top height) is a problem.
* **The black box in front of slots 1–2** (the hub?) must stay **below about 40 mm** so it doesn't block the view of the cell tops.
* **Your venue has coloured stage lighting.** Part 10.3 explains how to make the measurement stable under it.

### 0.2 The hardware
```
 Arduino USB Camera (5 cm in front) ──────USB──┐
                                                 ├── powered USB-C hub ── UNO Q ── Wi-Fi ── browser (dashboard :7000)
 USB-C PD power supply ──────────────────────────┘          │                   └─ internet ── Aiven PostgreSQL
                                                            └─ Qwiic ── Modulino Buzzer ── Thermo ── Knob
```

| Hardware | Used? | Job |
|---|---|---|
| Arduino UNO Q (in its cradle) | ✅ | Everything: vision, rules, AI, dashboard, database (Linux side); Modulinos and LED matrix (STM32 side) |
| **Arduino USB Camera** (on its own base, 5 cm in front of the foundation) | ✅ | Looks across the cell tops against the orange screen |
| Powered USB-C hub + PD supply | ✅ | USB port for the camera, power for everything |
| Modulino Knob, Thermo, Buzzer (in their cradles) | ✅ | Scan / calibrate; air temperature and humidity; sounds |
| Jetson Orin Nano | ⛔ spare | Only **Plan b** (Part 9.4) |
| Logitech C922 | ⛔ | Not used |

Nothing else is needed: no tape, torch, calipers, hairdryer or IR thermometer.

### 0.3 Two facts about the Arduino camera (already handled in the code)
1. **It cannot focus closer than about 20 cm** (its minimum focus distance). Placing it 5 cm in front of the foundation puts the cells at 20 cm, so they are sharp. Even if it ends up a bit closer, the slight blur is handled: I tested a blurred, off-centre, turned simulated camera, and the 0.6 mm cell reads +0.55 to +0.70 mm in every slot.
2. **It has an LED ring light.** It's **off by default**: it draws extra current through the hub, which makes drop-outs more likely. Switch it on only if the screen looks too dark (Part 10.3).

### 0.4 What is tested and what is not
* **Tested here, with a simulated camera of your foundation:**
  * the 0.6 mm cell found in every slot, with neighbours at about 0, including with the lens **below** the cell tops,
  * camera bumps caught by the screen edges alone,
  * RESEAT → SWELL → OK, plus MISSING, OBSTRUCTED, CAMERA_MOVED and THERMAL,
  * a free-standing camera 15 mm off-centre and turned 5°,
  * small camera nudges (slide, turn, roll, tilt) corrected automatically, big knocks flagged, Re-anchor restoring correct readings,
  * the placement guide giving the right directions, and converging in 2 rounds when followed imprecisely,
  * 20 automatic tests pass,
  * the full app running in a browser.
* **Not tested (I have no UNO Q or camera):** the App Lab menus, the Bridge, the Web UI brick, the Modulino calls and the real camera. I also couldn't confirm the camera's exact controls (ring light, manual focus) or whether it has a tripod thread. Its specs come from Arduino's product listing. Part 17 covers the likely problems.

### 0.5 The project folder

| Folder / file | What it is | Where it goes |
|---|---|---|
| `python/main.py` | the main program | App Lab app → `python/` |
| `python/breathe/*.py` | measurement, rules, AI, database code | App Lab app → `python/breathe/` |
| `python/config/station.yaml` | **all settings** (your foundation's numbers are already in it) | App Lab app → `python/config/` |
| `python/requirements.txt` | Python libraries App Lab installs for you (not OpenCV/numpy: App Lab's image already has them) | App Lab app → `python/` |
| `python/requirements-native.txt` | Python libraries for running outside App Lab (board venv, your Mac) | App Lab app → `python/` |
| `python/vision_service.py` | Plan a′ / b camera program that runs outside App Lab | App Lab app → `python/` |
| `sketch/sketch.ino` | microcontroller program | App Lab app → `sketch/` |
| `assets/` | the dashboard | App Lab app → `assets/` |
| `tools/` | smoke test, report, Aiven check, service installer, USB power-saving fix (`harden_usb.sh`) | App Lab app → `tools/` |
| `tests/` | automatic tests (optional, on your Mac) | App Lab app → `tests/` |
| `AGENTS.md`, `docs/CODEX_LOG.md` | for the "Best use of Codex" prize | App Lab app root / `docs/` |
| `app.yaml.example`, `sketch/sketch.yaml.example` | reference only; App Lab writes the real ones | do not rename |

---

## Part 1: Checklist

- [ ] The printed **BREATHE foundation** with the screen, holder, cradles and camera stand
- [ ] 4 normal cells (42.0 mm) + 1 fault cell (42.6 mm)
- [ ] Arduino **UNO Q**, **Arduino USB Camera**
- [ ] **Powered USB-C hub** + **USB-C PD supply** (≥ 5 V / 3 A)
- [ ] **Modulino Knob, Thermo, Buzzer** + Qwiic cables
- [ ] **USB-C data cable** (first UNO Q setup) and your **Mac**
- [ ] Mac and board on the **same Wi-Fi**

---

## Part 2: Install the software on your Mac

### 2.1 Arduino App Lab
1. 🌐 **https://www.arduino.cc/en/software** → **Arduino App Lab** → download for your system.
2. Open the downloaded `.dmg` and drag **Arduino App Lab** into **Applications**.
3. The first time, open *Applications*, **control-click** Arduino App Lab → **Open** → **Open** (macOS asks once because it was downloaded from the internet). If macOS asks to allow it to find devices on your local network, click **Allow**.
4. Check it starts.

### 2.2 `ssh` and `scp`
💻 MAC terminal
```bash
ssh -V
```
You should see something like `OpenSSH_9.x`. macOS always includes `ssh` and `scp`.

### 2.3 (Optional) Text editor
**VS Code** (https://code.visualstudio.com, download the Mac version, drag it into Applications) makes editing `station.yaml` and `.env` easy. You can also edit them on the board with `nano` (Part 8.1).

---

## Part 3: Put the project on your Mac

1. Download **`breathe-vision.zip`** (the file I sent).
2. Double-click it in **Downloads**: macOS unzips it into a folder `breathe-vision`.
3. It should be at `~/Downloads/breathe-vision` (the `Downloads` folder in your home folder). If you put it elsewhere, use that path below.

---

## Part 4: First-time setup of the UNO Q

1. Plug the UNO Q **directly** into your Mac with the USB-C data cable (**no hub yet**).
2. 🧩 App Lab finds the board and starts the **setup wizard**:
   * **Board name:** `breathe`
   * **Password:** choose one and **write it down** (Linux user `arduino`; used for SSH and `sudo`)
   * **Wi-Fi:** venue Wi-Fi and its password
   * **Updates:** accept them and wait; don't unplug.
3. Write down the **IP address** (`<board-ip>`): App Lab shows it, or type `hostname -I` in the board terminal after Part 5 (first number).

> On venue Wi-Fi `breathe.local` often fails. Use the IP address.

---

## Part 5: Terminal on the board (SSH)

💻 MAC terminal
```bash
ssh arduino@breathe.local
```
(or `ssh arduino@<board-ip>`). Type `yes` the first time, then the password (invisible while you type).

**If Terminal goes quiet and nothing happens** (cursor on the next line for more than ~20 s), your Mac can't reach the board. Press **control+C**, then work through these in order:
1. See where it stops:
   ```bash
   ssh -v arduino@breathe.local
   ```
   If the last line is `Connecting to breathe.local [address] port 22.`, the board isn't answering.
2. Force IPv4, or use the IP address from App Lab:
   ```bash
   ssh -4 arduino@breathe.local
   ```
   ```bash
   ssh arduino@<board-ip>
   ```
3. Check that your Mac can reach the board at all:
   ```bash
   ping -c 3 <board-ip>
   ```
   If every line says `Request timeout`, the Wi-Fi is blocking devices from talking to each other ("client isolation", common at events). Ask the organisers for a network without it (often a "makers" or "devices" network), or put the board and your Mac on a phone hotspot. The dashboard needs this too.
4. Turn off any **VPN** on the Mac.
5. If you use VS Code's terminal or iTerm instead of Terminal: *System Settings → Privacy & Security → Local Network* → switch that app **on**.
6. If ping works but SSH still hangs, check whether SSH answers:
   ```bash
   nc -vz <board-ip> 22
   ```
   If it's refused or times out, the board's SSH service isn't running. Wait a few minutes after a fresh setup or update, then try again.

**Clue:** if App Lab can see the board **over Wi-Fi**, the network path works, so the problem is in steps 2, 4 or 6.

🟦 BOARD terminal: install the camera tools and Python environments:
```bash
sudo apt update
```
```bash
sudo apt install -y v4l-utils python3-venv python3-pip
```
**A blue "Daemons using outdated libraries — Which services should be restarted?" screen may appear.** That's normal: keep the default ticks and press **return** to choose **<Ok>** (press **tab** first if <Ok> isn't highlighted; the mouse doesn't work there). The install then finishes.

Type `exit` to leave.

---

## Part 6: Create the App Lab app and copy in the code

### 6.1 Create the app
🧩 **My Apps → Create new app** → name **`breathe-vision`**.

### 6.2 Find its folder
🟦 BOARD terminal
```bash
ls ~/ArduinoApps
```
You should see `breathe-vision` (if the name differs, use that name below). If the folder isn't there:
```bash
find ~ -name app.yaml -path "*breathe*" 2>/dev/null
```

### 6.3 Copy the files
💻 MAC terminal: go into the project folder:
```bash
cd ~/Downloads/breathe-vision
```
Then copy everything (it asks for the board password):
```bash
scp -r python sketch assets tools tests docs db AGENTS.md GUIDE.md arduino@breathe.local:~/ArduinoApps/breathe-vision/
```
This replaces App Lab's empty `python/main.py` and `sketch/sketch.ino`. It does **not** touch `app.yaml` or `sketch/sketch.yaml`, which App Lab manages.

🟦 BOARD terminal: check:
```bash
cd ~/ArduinoApps/breathe-vision && ls -R | head -50
```
You should see `app.yaml`, `python/main.py`, `python/breathe/vision.py`, `python/config/station.yaml`, `sketch/sketch.ino`, `sketch/sketch.yaml` and `assets/index.html`.

### 6.4 Add the Web UI brick
🧩 Reopen the app → **Add Bricks** → **Web UI** (`arduino:web_ui`). Add nothing else.

**Then copy the dashboard files again.** Adding the brick can make App Lab write its own placeholder page into `assets/`, replacing ours (you'd see a blank page whose source starts with an Arduino `SPDX-FileCopyrightText` comment). In a Mac Terminal window:
```bash
cd ~/Downloads/breathe-vision && scp -r assets arduino@<board-ip>:~/ArduinoApps/breathe-vision/
```
Check on the board; this should print a number above 0:
```bash
grep -c "BREATHE" ~/ArduinoApps/breathe-vision/assets/index.html
```

### 6.5 Add the Modulino library
🧩 Sketch → **Libraries** → search **`Arduino_Modulino`** → **Install / Add**. If App Lab says `Arduino_RouterBridge` or `Arduino_LED_Matrix` is missing, add those too. If the Thermo has a **GXHT30C** chip (printed on its back), see Part 17, problem "thermo=0".

---

## Part 7: Put everything into the foundation (board unplugged)

1. **UNO Q** into its cradle (left), USB-C port towards the cable gap.
2. **Modulinos:** chain them **UNO Q Qwiic → Knob → Buzzer → Thermo**. The order doesn't matter to the software; each Modulino has its own address.
   * **Knob** and **Buzzer** go in their cradles. Put the knob wherever it's easiest to press without reaching into the camera's view.
   * The **Thermo** goes in its **pocket right next to the battery holder**, so it reads the air at the module.
   * Keep the Thermo and its cable **lower than the cell tops** and out of the line of sight between the camera and the cells.
   * You can slide the Thermo in or re-seat any Qwiic cable while everything is running: the board looks for missing Modulinos every 5 seconds.
3. **Hub:** put it in place but **don't plug it into the UNO Q yet** (step 5). **Place the hub off the foundation, or keep it lower than about 40 mm.** Nothing between the camera and the cells may stick up into the line of sight to the cell tops.
4. **Camera:** plug the **Arduino USB Camera** into the **hub** and stand it **about 5 cm in front of the foundation** on the centre line (Part 10.2 has the details).
5. **Power, in this order:** plug the **PD supply into the hub's power input** (*PD IN*) **first**, wait 5 s, and only **then** plug the hub's cable into the UNO Q. (The other way round, some hubs give the board too little power and its Wi-Fi never comes up.) Wait **about 2 minutes** before trying `ping` or `ssh`: Linux and Wi-Fi take that long. The LED matrix may stay dark until the app is started; that's normal.
6. 🧩 App Lab now reaches the board over **Wi-Fi (Network Mode)**: select `breathe` in the network list.

🟦 BOARD terminal: check the camera:
```bash
v4l2-ctl --list-devices
```
The Arduino camera should be listed (its name may say *Arduino* or *USB Camera*) with `/dev/videoN` under it. **Ignore the two "Qualcomm Venus" entries** (the video codec, e.g. `/dev/video0` and `/dev/video3`). The camera is the other entry; it may just be called **"Web Camera"** (e.g. `/dev/video1` and `/dev/video2`). The software finds it by itself.

---

## Part 8: First run in **simulator mode** (no camera needed)

### 8.1 Switch to the simulator
🟦 BOARD terminal
```bash
nano ~/ArduinoApps/breathe-vision/python/config/station.yaml
```
Use the arrow keys to move. Under `camera:` change `  source: auto` to `  source: synthetic`. Save with **control+O**, then **return**, then exit with **control+X**.

### 8.2 Run
🧩 **Run** (▶). **The first run takes several minutes** (App Lab installs the Python libraries; it needs internet). The console should show `BREATHE sketch started`, `thermo=1 knob=1 buzzer=1` and `[main] vision ready: synthetic`. The LED matrix shows four short bars.

### 8.3 Dashboard
🌐 **`http://<board-ip>:7000`**. The header shows **"synthetic · UNO Q"** and a temperature appears within seconds.

### 8.4 Practise the whole flow
1. **Calibration → Start calibration**, then keep pressing the **big button** and read each screen. In simulator mode the wizard moves the cells **by itself** (reseats them, puts the taller cell in each slot), so you can see the whole sequence before doing it for real. It ends with **Calibration complete ✓**.
2. **Simulator → All normal**, then **SCAN** → **OK**, one beep, four low bars.
3. **Fault → 3**, then **SCAN** → **RESEAT slot 3**. **Reseat**, then **SCAN** → **SWELL**, three beeps.
4. **Nudge camera**, then **SCAN** → still **OK** (corrected automatically). **Bump camera**, then **SCAN** → **CAMERA_MOVED**. Then **Camera placement → Start live check**: it tells you to turn the camera back. **Camera back home** → ✅ and a beep. Or try **Re-anchor here**.
   **Badly placed camera** shows what the placement guide says before calibration.
5. **Turn the knob** (it clicks); **short-press the knob** to scan. **Long-press** (1.5 s) starts the calibration wizard; while it's running, a short press = the wizard's big button.
6. **Breathe on the real Thermo** in its pocket for 15 s: the dashboard air temperature and humidity jump.

✅ Then put `source:` back to **`auto`** (8.1) and delete the simulator calibration:
🟦 BOARD terminal
```bash
rm -f ~/ArduinoApps/breathe-vision/python/data/calibration.json ~/ArduinoApps/breathe-vision/python/data/baseline_raw.json ~/ArduinoApps/breathe-vision/python/data/models/if_v1.joblib
```
🧩 Stop and Run.

---

## Part 9: Hour-1 camera smoke test

### 9.1 The camera on the board, outside App Lab
🟦 BOARD terminal (3–10 minutes):
```bash
python3 -m venv ~/breathe-venv
```
```bash
~/breathe-venv/bin/pip install -r ~/ArduinoApps/breathe-vision/python/requirements-native.txt
```
🧩 **Stop the App Lab app** (only one program can use the camera at a time). Then:
```bash
cd ~/ArduinoApps/breathe-vision && ~/breathe-venv/bin/python tools/smoke_test.py
```
Expected: `camera device: …`, `controls that worked: …`, `frame size 1920x1080`, then `SMOKE TEST PASSED`. A different frame size is fine; the software uses whatever size the camera gives.

**Then switch off USB power-saving (once).** Linux can put USB devices into a power-saving sleep, a common cause of cameras randomly disappearing. This turns that off for good:
```bash
bash ~/ArduinoApps/breathe-vision/tools/harden_usb.sh
```
It ends with `USB power-saving is OFF` and lists the camera. Enter the board password if asked.
💻 MAC terminal: look at the picture:
```bash
scp arduino@breathe.local:/tmp/smoke.jpg ~/Downloads/
```
```bash
open ~/Downloads/smoke.jpg
```

### 9.2 Inside App Lab
`source: auto`, 🧩 **Run**, then check the dashboard header:
* **`camera · UNO Q`** → ✅. Skip 9.4.
* **`service · UNO Q`** or **`VISION OFFLINE`** → do 9.4.

### 9.3 Camera controls
Under the live view: `camera 1920×1080 · autofocus off ✓ · manual focus ✓ · manual exposure ✓ · white balance ✓ · ring light: …`.
* **manual exposure ✗**: the camera keeps changing brightness. Calibrate under the same lighting you will demo in.
* **autofocus off ✗ / manual focus ✗**: autofocus stays on. It will sit at its nearest setting, which is fine. Recalibrate if sharpness suddenly changes.
* To see every control the camera offers (stop the app first):
  ```bash
  v4l2-ctl -d $(ls /dev/v4l/by-id/usb-*video-index0 | head -1) --list-ctrls
  ```

### 9.4 Plan a′: camera program running natively on the UNO Q (only if 9.2 failed)
🟦 BOARD terminal
```bash
cd ~/ArduinoApps/breathe-vision && bash tools/install_service.sh
```
It should end with `SERVICE OK`, and it now starts at every boot (log: `journalctl -u breathe-vision -f`). 🧩 Stop and Run → header **`service · UNO Q`**. Still offline? Run:
```bash
ip -4 addr show docker0 | grep inet
```
Put `http://<that-address>:8765` **first** under `service_urls:` in `station.yaml`, then Stop and Run.

**Plan b (Jetson), only if 9.1 itself fails:** plug the camera into the Jetson. Then `scp -r python tools <user>@<jetson-ip>:~/breathe-vision/`, and on the Jetson run `python3 -m venv ~/breathe-venv`, `~/breathe-venv/bin/pip install -r ~/breathe-vision/python/requirements-jetson.txt` and `cd ~/breathe-vision && bash tools/install_service.sh`. On the UNO Q set `source: service` and add `- http://<jetson-ip>:8765` first under `service_urls:`. The camera then sits on the Jetson's stand position instead.

---

## Part 10: Camera mounting and the scene

### 10.1 The screen and the cells
Nothing to add. Keep the orange screen clean and uncovered. The cells are already dark. The software needs the **whole width of the screen** in view, because its left, right and top edges are the camera-moved reference.

### 10.2 Place the camera (the optimal position)

**20 cm is the camera's *minimum focus distance*, not its focal length.** Anything closer than 20 cm looks soft. The focal length is a few millimetres inside the lens, and the software already knows it from the 80° field of view. So the rule is: **put the edge being measured at about 20 cm from the lens.**

**Optimal position (use this):**

| | Value | How to set it without a ruler |
|---|---|---|
| **Sideways** | on the **centre line** (x = 90), pointing straight along it at the middle of the screen | Line the lens up with the foundation's centre **spine** (the bar between the UNO Q and the camera-stand area) and the middle of the orange screen |
| **Distance** | **lens front about 5 cm in front of the foundation's front edge** (y ≈ −52). The cells' back edge is then about 20 cm away, sharp. | The old camera stand is 26 mm deep: **two stand-depths** in front of the foundation's front edge |
| **Height** | **lens centre 49–51 mm above the table**, i.e. 3–5 mm above the cell tops | Look at the camera from the side at the cells' height: the lens centre should be just above the cell tops. Calibration reports the exact value. |
| **Never** | lens centre at **44–47.7 mm** (cell-top height) | Calibration warns you if this happens |

What this gives you at the default 1920×1080 (double the pixels at 4K):

| Lens position | Back edge distance | 0.6 mm cell | Focus |
|---|---|---|---|
| On the old stand (y = 32) | 117 mm | 6.7 px | soft (closer than 20 cm) |
| Your photo (just in front of the stand, y ≈ −20) | 170 mm | 4.6 px | slightly soft |
| **Optimal (y ≈ −52)** | **200 mm** | **3.9 px** | **sharp** |
| Further back (y = −100) | 250 mm | 3.2 px | sharp, but fewer pixels per mm |

* **Your current spot (photo) works too.** It's a little closer than 20 cm, so slightly soft, but the software handles that. Moving it back another 3 cm makes it sharp.
* **The old orange stand cube can stay.** At this distance it is below the camera's view.
* The camera runs at **1920×1080, 30 frames per scan** (a scan takes about 1–2 s). The 0.6 mm cell is about 3.9 px, which is plenty: each edge is measured to a small fraction of a pixel. 1080p also draws less power and puts less load on USB than 4K, so the camera is much less likely to drop out. 4K (`width: 3840`, `height: 2160`, `frames: 15`) is possible, but only use it if your power is rock-solid.
* **The camera stands loose on its own base, and that is OK.** Every scan measures how far the picture has moved (from the screen's edges) and corrects small moves automatically. That covers a slide of about 3 mm, a turn of about 0.8°, a roll of about 0.7°, or 3 mm closer or further. Only bigger knocks give **CAMERA_MOVED**. Then use the **Camera placement** panel (10.6) to bring it back, or press **Re-anchor**.
* `station.yaml` already has this position (`lens_xyz_mm: [90.0, -52.0, 49.5]`). If you place the camera somewhere else, put your rough guess there. Calibration fits the real distance, height, sideways offset (±2 cm) and turn (±15°).

### 10.3 Lighting at the venue (coloured stage lights)
* The camera measures the **red channel** (`channel: red` in `station.yaml`): the orange screen is bright there and the dark cells stay dark.
* **The ring light is off by default** (`ring_light: "off"`), because it draws extra current through the hub. If the stage lights change colour or brightness, the screen's brightness changes too, and the dashboard says **LIGHTING**. If that keeps happening, or the screen is too dark, try `ring_light: "on"`, Stop/Run, then **Add baseline scan** once and compare the edge confidence. Keep "on" only if it is clearly better *and* the camera doesn't drop out. (The dashboard shows "ring light: on set" or "not settable". If it says *not settable*, use the camera's own button if it has one.)
* If the cells' top surfaces look almost as bright as the screen, try `channel: gray` or `green` and compare the same way.

### 10.4 Exposure
After Step 2 of the calibration the dashboard shows **"screen brightness"**. Aim for **150–240** in the red channel.
* Below 120: `exposure_100us: 200`.
* Above 245 (burnt out): `exposure_100us: 50`.
Stop and Run after each change.

### 10.5 Keep the line of sight clear
Between the camera and the cells, nothing may stand taller than about **40 mm**. Watch the **black box in front of slots 1–2**, cables and hands. Behind the screen, people can move freely.

### 10.6 The Camera placement panel (use it every time you place or touch the camera)
🌐 Dashboard → **Camera placement** → **Start live check**. The panel updates about once a second while you move the camera:

| Panel shows | Meaning |
|---|---|
| ➡️ **Adjust the camera** + a list of steps | Do the **top** step (the biggest), watch the panel update, repeat. The amounts are approximate; just follow the live updates. |
| ✅ **Camera is in the optimal position. Now calibrate.** | (Before calibration) Close enough to the optimal spot. Calibrate now (Part 11). |
| ✅ **Within the automatic-correction range: OK to scan.** | (After calibration) Close enough to where it was calibrated. Scans are corrected automatically. **The buzzer beeps once** when you reach this, so you can watch the camera instead of the screen. |
| ⛔ **I can't see the orange screen / the cell tops** | Point the camera roughly at the screen first. |
| ⏳ **Hold the camera still for a moment…** | The picture is still changing: either you're moving the camera, or it's still adjusting itself. The steps are shown greyed out. **Let go and wait 3–5 seconds**; the directions firm up. |

The steps it can give, and what to do:

| Step | What to do |
|---|---|
| ↕ Move the camera **CLOSER / FURTHER** | Slide it straight towards / away from the cells |
| ↻ **Turn** towards the Modulinos / UNO Q | Rotate it on the table (or slide it sideways) |
| ⤒ **Tilt UP / DOWN** | Tilt the lens (or raise/lower the camera) |
| ⟲ **Rotate clockwise / anticlockwise** (as seen from behind it) | Level the camera |

**Before calibration** it guides you to the optimal position from 10.2. **After calibration** it guides you back to where you calibrated, which only needs to be within a few millimetres, not exact.

**Re-anchor here** (same panel): if you can't get the camera back, or you moved it on purpose, put the **4 normal cells** in place and press it. It re-learns the camera position and the edges in about 2 minutes. It **keeps** your noise level, alarm thresholds, fault-cell scale and the AI, so you don't redo the whole calibration.

**How to use it smoothly:** make **one** adjustment, **let go**, and wait for the panel to show ➡️ or ✅ again (3–5 s) before the next one. The panel judges the **median of the last few pictures**, rounds amounts to 5 mm or 0.5°, and won't change an instruction or a number for a tiny wobble. That's on purpose, so a glitchy camera or flickering stage lights don't make the advice jump around. It only says ✅ (and beeps) after the camera has been OK and steady twice in a row.

**If it keeps showing ⏳ although nobody touches the camera**, the camera itself keeps changing the picture. Look at the camera line under the live view:
* **autofocus off ✗:** the camera keeps refocusing. That's normal at first; it settles once the picture is steady.
* **manual exposure ✗:** the brightness keeps pumping. Steady lighting helps; avoid flashing stage lights shining straight onto the screen.
* **⚠ camera dropped out and reconnected N×:** a power or USB problem (Part 17). After every reconnect the camera needs a few seconds to settle.

Press **Stop live check** when done; the check uses some processor time.

---

## Part 11: Calibrate (about 20 minutes, guided)

Calibration teaches the station two things: **what your four normal cells look like** (including how much they vary when you take them out and put them back), and **how big 0.6 mm looks** in the picture. You do it once after setting up, and again only if the foundation is moved or the lighting changes a lot.

The dashboard's **Calibration** card walks you through it. Each screen tells you **what to do with your hands**, then you press **one big button** (or **short-press the knob**). After each step it tells you, in plain words, whether it worked and what to do if not. You can't get it wrong: if something isn't right, it says so and the button becomes **Retry**.

**Before you start**
* Have the **4 normal cells (42.0 mm)** and the **taller fault cell (42.6 mm)** at hand. You'll be told when to use which.
* Place the camera with **Camera placement** until it shows ✅ (Part 10.6), then press **Stop live check**.
* Lights as they'll be during the demo.

**What the steps look like** (so you know what's coming):

| Step | What you do | What the station does | Time |
|---|---|---|---|
| **Get ready** | Put the 4 normal cells in slots 1–4, pushed down | – | – |
| **1. Sharpen** | Nothing: hands off | Finds the sharpest focus | ~1 min |
| **2. Learn the layout** | Nothing: hands off | Finds the screen, the cells and the camera's position | ≤ 1 min |
| **3. Normal cells** (8 rounds) | Round 1: hands off. Rounds 2–8: **lift all four cells a little and push them firmly back down**, then press the button | Takes 4 pictures per round; at the end works out the variation and trains the AI | ~4 min |
| **4. Show it 0.6 mm** (4 slots × 3 tries) | Swap the **taller cell** into the highlighted slot (the screen shows which), press **Measure**; between tries lift it slightly and push it back down. The LED matrix also lights up the slot to use | Measures the taller cell in every slot | ~5 min |
| **5. Final test** | Put the normal cell back, all four normal | A test scan: should say **OK** | ~5 s |

**Possible messages and what to do**

| The wizard says | What to do |
|---|---|
| "The lens is level with the cell tops…" | Raise the camera so the lens is a few mm above the cells, then Retry |
| "I can't see the whole orange screen…" | Use Camera placement so the full screen width is in the picture, then Retry |
| "Slot N is hard to see…" | Check nothing blocks that slot (cables, hub, a hand) and the cell is pushed down, then Retry |
| "Slot(s) … look a bit unclear" | Usually light shining on the cell tops; you can carry on |
| "The cells vary too much when re-inserted…" | Push each cell firmly and **straight** down every time, then redo the step (it restarts from round 1 by itself) |
| "I don't see a taller cell in slot N…" | The taller cell must be in the highlighted slot, the other three normal, all pushed down |
| "The other slots moved by …" | Something else moved: push all cells down, carry on |
| "Test scan says RESEAT/SWELL…" | The taller cell is still in, or a cell isn't pushed down. Fix it and press Test scan again |

**Skip:** on step 1 you can skip focusing (fine for most cameras). On step 4 you can skip a slot; its size is then taken from the other slots. Measuring all four is better.
**Cancel:** stops the wizard; anything already finished is kept.

The calibration is saved on the board and survives restarts. **If the camera is moved:** small moves are corrected automatically. After a bigger knock (**CAMERA_MOVED**), use **Camera placement** to bring it back, or press **Re-anchor here** (about 2 minutes, all 4 normal cells in place). Only if the **foundation** itself moved, or the lighting changed a lot, run the calibration again.

**Advanced:** the old individual buttons are still there under **Advanced (individual calibration steps)**, plus a status line with the technical numbers.

---

## Part 12: Aiven PostgreSQL

### 12.1 Create the database
1. 🌐 **https://console.aiven.io** → sign up (free).
2. **Create service → PostgreSQL → Free plan →** name **`breathe-pg`** → **Create**. Wait for **Running**.
3. **Overview → Connection information**: copy the **Service URI** and download the **CA certificate**, saved as **`ca.pem`**.

### 12.2 Give them to the board
On your Mac, in `breathe-vision/python/config/`:
Finder hides files whose names start with a dot, so make `.env` in Terminal:
💻 MAC terminal
```bash
cd ~/Downloads/breathe-vision && cp python/config/.env.example python/config/.env && open -e python/config/.env
```
1. TextEdit opens the file. Replace the example after `AIVEN_PG_URI=` with your **Service URI** (one line, no spaces), then press **command+S** and close it.
2. Move the downloaded **`ca.pem`** into the same folder:
```bash
mv ~/Downloads/ca.pem ~/Downloads/breathe-vision/python/config/ca.pem
```

💻 MAC terminal
```bash
cd ~/Downloads/breathe-vision && scp python/config/.env python/config/ca.pem arduino@breathe.local:~/ArduinoApps/breathe-vision/python/config/
```
**Never** share `.env` or put it on GitHub. It holds the database password.

### 12.3 Check
🟦 BOARD terminal
```bash
cd ~/ArduinoApps/breathe-vision && ~/breathe-venv/bin/python tools/aiven_check.py
```
Expected: `connected …`, `TLS: (True, 'TLSv1.3')`, `AIVEN OK`. 🧩 Stop and Run → the header shows **"Aiven: synced"**. **Show data from Aiven** shows `pack_health` and the latest scans.

> The Free plan may **power off** after a period with no activity. **Open the Aiven console about 30 minutes before judging** and make sure the service is *Running*.

---

## Part 13: Test everything

| Do this | Expected |
|---|---|
| All normal | **OK** |
| Fault cell into any slot | **RESEAT slot N** → reseat → **SWELL slot N +0.6 mm**, 3 beeps |
| Seat a normal cell crooked: push only one side down, so it rests on the cradle's rail at the other | **RESEAT** (tilted) |
| Take a cell out | **MISSING** |
| Hand between the camera and the cells | **OBSTRUCTED** (no cell verdict) |
| Hold your hand above the screen to shade it (not in the camera view) | **LIGHTING** |
| Nudge the camera slightly (a millimetre or two) | Still **OK** (corrected automatically) |
| Knock the camera clearly out of place | **CAMERA_MOVED** → Camera placement panel back to ✅, or **Re-anchor here** |
| **Breathe on the Modulino Thermo** in its pocket for 15 s, leaning in **from behind the screen** (the camera can't see behind it), then step back and scan **at once** | **THERMAL … geometry unchanged** + **condensation-risk** note |

**Why breathing works:** breath is about 30–34 °C and almost saturated with water. The air reading rises faster than 1 °C/min, and the dew point jumps above the modelled surface temperature. The cells do not change shape, so the honest verdict is "air-temperature event, geometry unchanged".

**τ (thermal time constant):** you can't measure it without an IR thermometer. Leave `tau_module_s: 300`; the dashboard labels the surface value "est. (model)". Say "τ assumed" in your post.

**Repeatability table:** do 10 swap cycles (fault in, reseat, scan, out, scan), then:
🟦 BOARD terminal
```bash
cd ~/ArduinoApps/breathe-vision && ~/breathe-venv/bin/python tools/report.py
```
It saves `docs/results_table.md`. Quote **your measured σ**.

---

## Part 14: Demo day

**If someone knocks the camera during the demo:** the dashboard says CAMERA_MOVED and gives no verdict, which is itself a good thing to show. Open **Camera placement → Start live check**, follow it until the beep, and carry on. If you can't, press **Re-anchor here** with the 4 normal cells in place (about 2 minutes).

**Before judging:** run the app once on the venue Wi-Fi; check the Aiven service is *Running*; do one OK scan with normal cells. If the camera moved, use Camera placement or **Re-anchor here** (about 2 min). If the foundation moved or the stage lighting is very different from when you calibrated, run the calibration wizard again (Part 11, about 20 min).

**The 3-minute script:**
- **0:00** Problem: swelling is an early warning of cell failure; from 18 Feb 2027 the EU battery passport is mandatory.
- **0:25** Short-press the knob → four low bars on the UNO Q's LED matrix, one beep, dashboard **OK**, heights within about ±0.02 mm, air temperature, dew point.
- **0:50** A judge puts the 42.6 mm cell in **any** slot → **RESEAT slot N**. Reseat → **SWELL slot N +0.60 mm**, three beeps, action text. **Show data from Aiven**: the row is there.
- **1:40** Swap back → OK.
- **1:55** **Breathe on the Thermo** (in its pocket next to the module, leaning in from behind the screen) for 15 s, step back, then scan → **THERMAL … geometry unchanged**, plus the condensation note. Show the chart.
- **2:30** Hand in view → **OBSTRUCTED – no verdict**. Show "AI score … ms on-device", Aiven `pack_health`, `docs/CODEX_LOG.md`.
- **2:55** Close.

---

## Part 15: Best use of Codex

1. `AGENTS.md` tells Codex the layout, your foundation's constants and the rules.
2. Put the project on GitHub **without** `python/config/.env`, `ca.pem` and `python/data/` (the `.gitignore` already excludes them).
3. Use Codex for new pieces (ideas in `docs/CODEX_LOG.md`), one module at a time, each with a pytest.
4. Log every prompt in `docs/CODEX_LOG.md` and commit each change separately. Say that the starting code was written with Claude from your spec.

---

## Part 16 (optional): run and test on your Mac

1. Install **Python 3.12+** for macOS from https://www.python.org/downloads/ (open the `.pkg`, click through). Then double-click **Install Certificates.command** in *Applications → Python 3.x*.
2. 💻 MAC terminal, inside `breathe-vision`:
```bash
cd ~/Downloads/breathe-vision && python3 -m pip install -r python/requirements-native.txt pytest
```
```bash
python3 -m pytest -q tests
```
Expected: `20 passed` (about 3–4 minutes).
3. Set `source: synthetic` in `python/config/station.yaml`, then:
```bash
cd ~/Downloads/breathe-vision/python && python3 main.py
```
4. 🌐 **http://localhost:7000**. The thermometer is faked and **Breathe on sensor** simulates a breath. **control+C** in Terminal stops it.

---

## Part 17: Troubleshooting

| Problem | What to do |
|---|---|
| Board not found over USB | Another USB-C cable (must carry data) or another port; no hub during first setup. |
| `breathe.local` not found | Use the IP address. |
| `ssh` hangs silently | Part 5, "If Terminal goes quiet". |
| `ping` works but the dashboard doesn't load | Allow your browser under *System Settings → Privacy & Security → Local Network*. |
| Sketch error about `begin()` returning `void` | In `sketch.ino` replace `haveThermo = thermo.begin();` with `thermo.begin(); haveThermo = true;` (same for knob and buzzer). |
| `Arduino_Modulino.h: No such file` | Part 6.5. |
| `thermo=0` in the console | Push the Qwiic cables in fully. **GXHT30C** Thermo: install the library from GitHub `main` (https://github.com/arduino-libraries/Arduino_Modulino → *Code → Download ZIP* → App Lab library panel → install from ZIP). |
| Dashboard is a blank page; `curl -s http://<board-ip>:7000/ | head -5` shows an Arduino `SPDX-FileCopyrightText` comment | App Lab's placeholder replaced our page: copy `assets/` again (end of Part 6.4), restart the app, reload with command+shift+R. |
| Dashboard won't load | App running? Web UI brick added? `http://<board-ip>:7000`, same Wi-Fi? |
| `VISION OFFLINE` | Hub powered by the PD supply? Camera on the hub? `v4l2-ctl --list-devices`? Plan a′ (9.4)? |
| Header says **"camera reconnecting…"** | The camera dropped off USB for a moment. The app keeps reconnecting by itself and beeps once when it's back. A scan during a drop-out gives no verdict (never a wrong one) and is redone automatically. If it happens often: run `tools/harden_usb.sh` (9.1), keep `ring_light: "off"` and 1080p, use the power order from Part 7, try another hub port, and check what `sudo dmesg \| grep -i -E "usb\|uvc\|over-current" \| tail -30` says on the board. |
| Dashboard shows "⚠ camera dropped out and reconnected N×" | Same as above: it recovered, but something is cutting the camera's power or USB link. |
| Air temperature jumps to nonsense or stops updating | Re-seat the Thermo's Qwiic cable; the board finds it again within 5 s. Single glitch readings are ignored automatically. |
| Camera busy | Only one of {App Lab app, `vision_service.py`, `smoke_test.py`} at a time. `sudo systemctl stop breathe-vision` stops the service. |
| "lens … too close to the cell tops" | Raise the camera so the lens centre is 49–51 mm above the table (10.2), then Fit geometry again. |
| "screen edges not found" | Aim so the whole screen width and its top edge are in the picture. |
| Edge confidence < 0.6 | Try the ring light on/off and `channel: red/gray/green` (10.3); exposure (10.4); check the camera is ≥ 5 cm in front of the foundation (10.2). |
| Scans or calibration too slow | Set `width: 1920`, `height: 1080`, `frames: 30` in `station.yaml` (0.6 mm ≈ 3.9 px; still works). |
| Fit error > 1 px or green dots on bumps | Check `slot_left_x` and the screen numbers in `station.yaml` against your drawing, then Fit again. |
| Neighbour of the fault cell reads raised | Same as above; look at the overlay picture. |
| σ_reseat > 0.1 mm | Press the cells down firmly every time; `frames: 60`. |
| `LIGHTING` on its own | The stage lights changed: use the ring light (10.3) and recalibrate under the demo lighting. |
| `CAMERA_MOVED` | The camera moved more than can be corrected: Camera placement panel → follow it to ✅, or **Re-anchor here**. If it keeps happening with nobody touching anything: something moving right behind the screen's side edges (people, cables) can confuse the check, so keep that area calm. |
| Placement panel says "can't see the screen" | Point the camera roughly at the orange screen and make sure the cells sit in front of it. |
| Placement panel never reaches ✅ before calibration | The amounts are estimates. Get each line within its tolerance and calibrate; the calibration absorbs the rest. |
| `ANOMALY` too often | 30+ baseline scans, then Finish again. |
| Bridge hangs / app won't start | 🟦 `arduino-app-cli system cleanup`, then Run. |
| Aiven `AIVEN_PG_URI not set` | `.env` missing or misnamed (12.2); restart the app. |
| Aiven certificate error | Re-download `ca.pem` into `python/config/`. |
| Aiven or Wi-Fi down during the demo | Scans wait in `python/data/outbox.db` and upload later. |
| App "failed to start"; `sudo docker logs --tail 80 breathe-vision-main-1` shows `No solution found … there is no version of X==…+…` | App Lab's image already ships that library pinned. Remove its line from `python/requirements.txt`, then Run again. |
| App "failed to start", any other reason | On the board: `sudo docker logs --tail 80 breathe-vision-main-1` shows the Python error at the bottom. |
| Changed `station.yaml`, nothing happened | Stop and Run the app. |

**Logs:** App Lab console; `journalctl -u breathe-vision -f` (Plan a′ / b); every scan in `python/data/scans/YYYYMMDD.jsonl`; a picture for every non-OK verdict in `python/data/frames/`.

---

## Part 18: How the measurement works (for your write-up)

1. **Averaging:** 30 frames at 1920×1080, red channel. Damaged frames (blank, cut off, sudden brightness jumps) are skipped, and if the camera reconnects part-way through, the average starts again so frames from before and after a drop-out are never mixed.
2. **Geometry fit:** with four normal cells, the program reads the silhouette in every column (walking up from the dark holder until the orange screen begins) and fits a 3-D pinhole model of your foundation: camera centre, lens height, distance and roll. It tries lens heights both above and below the cell tops and keeps the best. The focal length comes from the camera's 80° field of view.
3. **Column masks from the 3-D model:** a column is used for slot *i* only if the silhouette there is slot *i*'s own top edge, **no other cell's top can project into it**, no terminal does, and it is clear of rounded corners and blur. A taller neighbour can never leak in.
4. **Sub-pixel edges** in each column, with a confidence measure that tolerates soft focus.
5. **Per-column baseline** (median of 30 reseated scans). Each column's change is turned into millimetres using its own depth, robustly averaged per cell and per half (for tilt), then corrected by the fault-cell scale.
6. **Loose-camera handling:** the printed screen's left/right edges (in two bands, which give the roll, since turning the camera keeps vertical edges vertical) and its top edge are tracked to a fraction of a pixel. From them, every scan estimates how the picture shifted, scaled and rotated since calibration, and samples the cell edges where they are now. Small moves are corrected; big ones are flagged. The Camera placement panel turns the same measurements into "closer / turn / tilt / rotate" directions.
7. **Camera watchdog:** every 8 s while idle, the app reads one frame. A camera that dropped off USB is reconnected in the background (it finds it again even if it comes back under a new `/dev/videoN`, then re-applies focus and exposure). A scan that hits a drop-out waits and retries up to 3 times, then reports "no verdict", never a wrong one.
8. **Rules** in a fixed order: station faults, missing, tilt, single-cell rise (reseat-then-confirm), uniform rise, thermal, watch, AI anomaly, OK. The **Isolation Forest** is trained on the board on normal scans only, and its alarm level is learned from out-of-fold scores.

**Honest limits:** a top silhouette cannot tell a lifted cell from a swollen one without reseat-and-confirm, and it cannot see side bulging. One air sensor next to the module cannot measure cell temperature (τ is assumed; the breath demo warms only the air). The camera works closer than its minimum focus distance. Real EV service uses BMS cell sensors, OEM swelling limits and certified high-voltage procedures. This is a scaled proof of concept for an automated, passport-linked visual check.

**Camera specs from:** [Arduino USB Camera docs](https://docs.arduino.cc/hardware/usb-camera/), [Arduino store](https://store.arduino.cc/products/usb-camera).
