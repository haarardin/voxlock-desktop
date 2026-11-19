# VoxLock Desktop

Native desktop UI for **local, real-time voice isolation** on Linux and Windows.
Powered by [VoxLock](https://github.com/arbazsiddiqui/voxlock) and built with
Python, PySide6 and ONNX Runtime.

**Status: manually testable MVP.** UI, voice enrollment, audio routing, levels
and five-second before/after recordings are implemented. Actual audio hardware
operation has **not** been verified on a real Linux or Windows machine yet.

## Linux: Debian 13 / KDE / PipeWire

Requirements: Python 3.10+, microphone, running PipeWire with pipewire-pulse
(or PulseAudio), and pulseaudio-utils.

~~~bash
sudo apt update
sudo apt install python3-venv pulseaudio-utils
git clone https://github.com/haarardin/voxlock-desktop.git
cd voxlock-desktop
git checkout feat/cross-platform-desktop-mvp
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
voxlock-desktop
~~~

The first time the processing starts, VoxLock downloads approximately 74 MB
of ONNX weights into the Hugging Face model cache, if needed.
To download models in advance, run:

~~~bash
voxlock download
~~~

1. Select your real microphone and record an **8-second voice profile**.
2. Click **Start processing**; wait for the enabled status.
3. In Discord, Telegram or the browser select **VoxLock_Microphone**
   (display name **VoxLock Microphone**) as your input.
4. To compare, click **Record comparison (5 seconds)** and open the
   locally saved before/after WAVs using the interface.
5. Stop the app when finished; its virtual audio modules are unloaded.

The virtual microphone is only available while processing is running.
It uses PulseAudio-compatible modules available through PipeWire. No root
permissions are needed to run the application. You can cancel startup
while the model is loading, although an in-progress download may need
to finish before the worker exits.

## Windows 10/11

Requires Python 3.10+ (3.11 recommended), a real microphone, and a
**separately installed** virtual audio cable, e.g. [VB-CABLE](https://vb-audio.com/Cable/).

In PowerShell:

~~~powershell
git clone https://github.com/haarardin/voxlock-desktop.git
cd voxlock-desktop
git checkout feat/cross-platform-desktop-mvp
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[windows]"
voxlock-desktop
~~~

In VoxLock Desktop select the real mic under **Input** and the virtual
cable *playback* endpoint under **Output** (usually **CABLE Input (VB-Audio
Virtual Cable)**). In the calling application select the virtual cable
*recording* endpoint (usually **CABLE Output (VB-Audio Virtual Cable)**).

For safety, VoxLock Desktop only lists recognized **virtual cable**
playback endpoints; physical speakers and headphones are intentionally
excluded from the output selector. If no virtual output is found, install
and activate VB-CABLE first. Device names differ by driver and Windows
host API. VB-CABLE is not bundled or installed by VoxLock Desktop.

## Voice selection and privacy

For the recommended enrolled mode, the app saves an 8-second voice sample
locally and uses VoxLock's **model.stream(sample)** to select that voice.
No neural network training or upload of the microphone audio occurs.

The optional automatic first-speaker mode uses **model.live()**. It passes
unfiltered speech through during voice selection and may choose another
person. Avoid this mode if suppressing background voices from the first
second is important.

The model is downloaded from Hugging Face on initial use. Processing is
otherwise local. The microphone is not uploaded. The voice profile and
five-second comparisons are saved only on request under:

- Linux: ~/.local/share/voxlock-desktop (or XDG_DATA_HOME/voxlock-desktop)
- Windows: %LOCALAPPDATA%/VoxLockDesktop

The comparison WAVs **contain voice recordings**. Delete them when done;
each new comparison overwrites the previous one.

## Design reference

Save the UI image from the chat in **[assets/reference/](assets/reference/README.md)**,
for example under the name **voxlock-desktop-concept.png**.
The running desktop UI is implemented in **src/voxlock_desktop/ui.py**.

## Development

~~~bash
python -m pip install -e ".[windows]" pytest
python -m pytest -q
python -m compileall -q src
~~~

Project layout:

~~~text
src/voxlock_desktop/
  app.py        Qt application entry point
  ui.py         Styled interactive interface
  style.py      Shared dark styling for Linux/Windows
  engine.py     VoxLock worker, profile capture, bounded output FIFO
  devices.py    PipeWire/PulseAudio and Windows PortAudio backends
assets/reference/
tests/
.github/workflows/
~~~

## Known limitations

This is a **source-based MVP**: no .deb, .exe installer or autostart service
yet. VoxLock documents 24 ms **algorithmic** latency, but full end-to-end
latency is unmeasured and larger. A slow CPU can cause dropouts. Devices
may reject the selected audio format. Windows virtual mic needs an external
driver. On Linux, crash leftovers can be inspected with
**pactl list short modules** and removed by module ID with **pactl
unload-module ID** only after confirming they belong to this app.

When processing fails, the app is designed to stop rather than
intentionally fall back to the raw mic. As with any experimental audio
application, verify what a call recipient actually hears before relying
on it for privacy-sensitive conversations.
