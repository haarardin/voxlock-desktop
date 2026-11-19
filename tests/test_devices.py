"""Test security-sensitive platform paths without requiring real hardware."""
import subprocess
import sys
from types import SimpleNamespace

import pytest
from voxlock_desktop import devices


def test_virtual_output_filter():
    assert devices.is_virtual_cable_output("CABLE Input (VB-Audio Virtual Cable)")
    assert devices.is_virtual_cable_output("Voicemeeter Input (VB-Audio)")
    assert not devices.is_virtual_cable_output("Speakers (Realtek(R) Audio)")
    assert not devices.is_virtual_cable_output("Headphones (USB Audio)")
    assert not devices.is_virtual_cable_output("HDMI Output")


def test_windows_does_not_offer_physical_outputs(monkeypatch):
    items = [
        {"name": "Microphone (USB)", "max_input_channels": 1,
         "max_output_channels": 0, "hostapi": 0, "default_samplerate": 48000},
        {"name": "Speakers (Realtek)", "max_input_channels": 0,
         "max_output_channels": 2, "hostapi": 0, "default_samplerate": 48000},
        {"name": "CABLE Input (VB-Audio Virtual Cable)", "max_input_channels": 0,
         "max_output_channels": 2, "hostapi": 0, "default_samplerate": 48000},
    ]
    fake = SimpleNamespace(
        query_devices=lambda index=None: items if index is None else items[index],
        query_hostapis=lambda: [{"name": "Windows WASAPI"}],
        RawInputStream=lambda **kw: pytest.fail("Must reject before capturing audio"),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    monkeypatch.setattr(devices, "is_windows", lambda: True)
    monkeypatch.setattr(devices, "is_linux", lambda: False)
    assert [x.key for x in devices.list_outputs()] == ["2"]
    with pytest.raises(RuntimeError, match="not speakers"):
        devices.WindowsSession("0", "1").open()


def test_linux_cleanup_when_remap_source_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(devices.shutil, "which", lambda c: "/usr/bin/" + c)
    def pactl(*args):
        calls.append(args)
        if args[:3] == ("list", "short", "sinks"):
            return ""
        if args[:2] == ("load-module", "module-null-sink"):
            return "129"
        if args[:2] == ("load-module", "module-remap-source"):
            raise subprocess.CalledProcessError(1, list(args), "failed")
        if args[:2] == ("unload-module", "129"):
            return ""
        raise AssertionError("unexpected pactl command: " + repr(args))
    monkeypatch.setattr(devices, "_pactl", pactl)
    with pytest.raises(subprocess.CalledProcessError):
        devices.LinuxSession("mock_microphone").open()
    assert ("unload-module", "129") in calls
