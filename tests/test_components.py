"""
Takt component tests. Runs under pytest, or directly:  python tests/test_components.py

Covers logic that must hold without a microphone or GPU: config robustness, disfluency / gate
behaviour, formatter, injector surrogate handling, hotkey event ordering, microphone-dead
recovery policy, and the HUD capsule geometry.
"""

import os
import sys
import tempfile
import threading
import time

import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ------------------------------------------------------------------------------ config
def test_config_defaults_and_corrupt_file():
    from src.core import config as cfgmod

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "app_config.yaml")
        orig = cfgmod.config_path
        cfgmod.config_path = lambda: path
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("hotkey: [this is: not valid yaml")
            cfg = cfgmod.load_config()
            assert cfg["hotkey"]["key"] == "alt_r", "defaults must be used for a corrupt file"
            assert any(n.startswith("app_config.yaml.bad") for n in os.listdir(tmp)), "corrupt file is quarantined"

            cfg["ui"]["accent_color"] = "#123456"
            cfgmod.save_config(cfg)
            assert cfgmod.load_config()["ui"]["accent_color"] == "#123456"

            with open(path, "w", encoding="utf-8") as f:
                f.write("ui:\n  accent_color: '#abcdef'\n")
            partial = cfgmod.load_config()
            assert partial["ui"]["accent_color"] == "#abcdef" and partial["audio"]["sample_rate"] == 48000
        finally:
            cfgmod.config_path = orig


def test_config_migrates_to_appdata_and_survives_updates():
    from src.core import config as cfgmod

    with tempfile.TemporaryDirectory() as tmp:
        app = os.path.join(tmp, "app")
        appdata = os.path.join(tmp, "roaming")
        os.makedirs(os.path.join(app, "config"))
        with open(os.path.join(app, "config", "app_config.yaml"), "w", encoding="utf-8") as f:
            f.write("ui:\n  accent_color: '#010203'\n")
        orig_dir, orig_env = cfgmod.app_dir, os.environ.get("APPDATA")
        cfgmod.app_dir = lambda: app
        os.environ["APPDATA"] = appdata
        try:
            target = os.path.join(appdata, "Takt", "app_config.yaml")
            assert cfgmod.config_path() == target
            cfg = cfgmod.load_config()
            assert os.path.exists(target), "legacy install-folder config is migrated"
            assert cfg["ui"]["accent_color"] == "#010203" and cfg["audio"]["sample_rate"] == 48000

            cfg["ui"]["accent_color"] = "#aabbcc"
            cfgmod.save_config(cfg)
            # Simulate an update/rebuild that replaces the install folder's config with defaults.
            with open(os.path.join(app, "config", "app_config.yaml"), "w", encoding="utf-8") as f:
                f.write("ui:\n  accent_color: '#ffbdd4'\n")
            assert cfgmod.load_config()["ui"]["accent_color"] == "#aabbcc"

            open(os.path.join(app, "portable"), "w").close()
            assert cfgmod.config_path() == os.path.join(app, "config", "app_config.yaml")
        finally:
            cfgmod.app_dir = orig_dir
            if orig_env is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = orig_env


# -------------------------------------------------------------------------------- uhm
def test_uhm_keeps_real_words_and_strips_fillers():
    from src.engine.dal_uhm import DALUhmEngine

    uhm = DALUhmEngine()
    assert uhm.strip_disfluencies("I like it, what kind of car is that actually") == \
        "I like it, what kind of car is that actually"
    assert uhm.strip_disfluencies("I kinda like how this is coming along") == \
        "I kinda like how this is coming along"
    assert uhm.strip_disfluencies("Do you know what time it is?") == \
        "Do you know what time it is?"
    out = uhm.strip_disfluencies("Um, I think we should, uh, build this tool, scratch that, build this engine.")
    assert out == "build this engine.", out
    assert uhm.strip_disfluencies("one two three scratch last word four") == "one two four"
    assert uhm.strip_disfluencies("the the cat sat uh on the mat") == "the cat sat on the mat"


def test_acoustic_gate_adapts_and_rejects_noise():
    from src.engine.dal_uhm import DALUhmEngine

    uhm = DALUhmEngine()
    sr = 48000
    rng = np.random.default_rng(1)
    quiet_speech = np.zeros(sr * 2, dtype=np.float32)
    quiet_speech[40000:60000] = rng.standard_normal(20000).astype(np.float32) * 0.04
    quiet_speech += rng.standard_normal(len(quiet_speech)).astype(np.float32) * 0.001
    gated = uhm.apply_acoustic_gate(quiet_speech, sr)
    assert 20000 < len(gated) < sr, "speech region kept, silence trimmed"

    noise = rng.standard_normal(sr * 2).astype(np.float32) * 0.001
    assert len(uhm.apply_acoustic_gate(noise, sr)) == 0, "noise-only buffer yields no speech"


# ---------------------------------------------------------------------------- formatter
def test_formatter_lightweight():
    from src.engine.formatter import ContextualFormatter

    f = ContextualFormatter()
    assert f.format("hello world this is a test comma and more") == "Hello world this is a test, and more."
    assert f.format("open main.py now") .startswith("Open main.py")
    # Unreachable Ollama must fall back instead of raising
    f.mode = "ollama"
    f.ollama_endpoint = "http://127.0.0.1:9"
    assert f.format("hello there my friend") == "Hello there my friend."


def test_formatter_smart_routing_and_fallback():
    from src.engine.formatter import ContextualFormatter

    f = ContextualFormatter(mode="smart_groq")          # no API key -> lightweight fallback
    long = "let's do monday actually no wednesday at two pm for the sync"
    assert f.format(long) == f.format_lightweight(long)
    calls = []
    f.groq_api_key = "k"
    f._call_smart = lambda mode, text: calls.append(text) or "Let's do Wednesday at 2:00 PM for the sync."
    assert f.format("hi there") == f.format_lightweight("hi there") and not calls  # short: no LLM
    assert f.format(long) == "Let's do Wednesday at 2:00 PM for the sync." and len(calls) == 1
    def boom(mode, text): raise OSError("offline")
    f._call_smart = boom
    assert f.format(long) == f.format_lightweight(long)
    assert "Wednesday" in f._system_prompt() and f.style == "clean"


def test_formatter_router_gates():
    from src.engine.formatter import ContextualFormatter

    clean = "please open the settings page and check the microphone"
    messy = "send it to bob wait no send it to alice tomorrow morning"
    f = ContextualFormatter(mode="smart_groq", groq_api_key="k", router="heuristic")
    calls = []
    f._call_smart = lambda mode, text: calls.append(text) or "SMART"
    # Heuristic gate: clean -> instant, no LLM; self-correction / repeats / long unpunctuated -> LLM
    assert f.format(clean) == f.format_lightweight(clean) and not calls
    assert f.format(messy) == "SMART" and len(calls) == 1
    assert f.format("we we should ship this on friday for sure") == "SMART"
    assert f.format(" ".join(["word%d" % i for i in range(30)])) == "SMART"
    assert f.format(" ".join(["word%d" % i for i in range(30)]) + ".") != "SMART"

    # Jev gate: payload shape, decision honoured, failure falls back to heuristic
    import src.engine.formatter as fm
    sent = {}
    answer = {"needs_smart_cleanup": False}

    def fake_http(url, payload=None, timeout=3.0, headers=None):
        sent.update(url=url, payload=payload, timeout=timeout, headers=headers)
        return {"answers": answer}

    orig = fm._http_json
    fm._http_json = fake_http
    try:
        j = ContextualFormatter(mode="smart_groq", groq_api_key="k", router="jev", typesafe_api_key="ts")
        calls2 = []
        j._call_smart = lambda mode, text: calls2.append(text) or "SMART"
        assert j.format(messy) == j.format_lightweight(messy) and not calls2   # Jev says clean -> instant
        assert sent["payload"]["model"] == "jev-latest" and sent["payload"]["state"] == messy
        assert sent["payload"]["questions"]["needs_smart_cleanup"]["type"] == "boolean"
        assert sent["headers"]["Authorization"] == "Bearer ts" and sent["timeout"] <= 1.5
        assert sent["url"] == "https://api.typesafe.ai/v1/systemone"
        answer["needs_smart_cleanup"] = True
        assert j.format(clean) == "SMART"                                      # Jev says messy -> LLM

        def boom(*a, **k): raise OSError("offline")
        fm._http_json = boom
        assert j.needs_smart(messy) and not j.needs_smart(clean)               # heuristic fallback
        j.typesafe_api_key = ""
        assert not j.needs_smart(clean)
    finally:
        fm._http_json = orig

    # Always smart gate: every dictation goes to LLM regardless of clarity
    a = ContextualFormatter(mode="smart_groq", groq_api_key="k", router="always_smart")
    acalls = []
    a._call_smart = lambda mode, text: acalls.append(text) or "SMART"
    assert a.format(clean) == "SMART" and len(acalls) == 1
    assert a.format(messy) == "SMART" and len(acalls) == 2


# ----------------------------------------------------------------------------- injector
def test_unicode_units_use_surrogate_pairs():
    from src.injector.keystroke import _utf16_units

    units = list(_utf16_units("a😀"))
    assert units == [0x61, 0xD83D, 0xDE00], [hex(u) for u in units]


# ---------------------------------------------------------------------------------- hook
def test_hook_events_are_ordered_and_alt_left_is_ignored():
    from src.core.hook import GlobalKeyboardHook, VK_LMENU, VK_RMENU

    order = []
    hook = GlobalKeyboardHook(hotkey="alt_r", mode="push_to_talk",
                              on_press=lambda: (time.sleep(0.05), order.append("press")),
                              on_release=lambda: order.append("release"))
    # Run only the dispatcher (no OS hook): a slow press callback must still finish before release
    import queue
    hook._queue = queue.Queue()
    t = threading.Thread(target=hook._dispatch_loop, args=(hook._queue,), daemon=True)
    t.start()
    hook._is_alt_hotkey = lambda: False          # don't inject real keystrokes during the test
    hook._trigger_press()
    hook._trigger_release()
    hook._queue.put(None)
    t.join(2)
    assert order == ["press", "release"], order

    assert hook._is_target_key(VK_RMENU, 0) and not hook._is_target_key(VK_LMENU, 0)


# ----------------------------------------------------------------------------- capture
def test_groq_key_falls_back_to_environment():
    from src.core import config as cfgmod

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "app_config.yaml")
        orig_path, orig_env = cfgmod.config_path, os.environ.get("GROQ_API_KEY")
        cfgmod.config_path = lambda: path
        try:
            os.environ["GROQ_API_KEY"] = "gsk_env_value"
            cfg = cfgmod.load_config()
            assert cfg["models"]["formatter"]["groq_api_key"] == "gsk_env_value"
            cfgmod.save_config(cfg)
            with open(path, encoding="utf-8") as f:
                assert "gsk_env_value" not in f.read(), "env-sourced key must not be written to disk"

            cfg["models"]["formatter"]["groq_api_key"] = "gsk_user_value"
            cfgmod.save_config(cfg)
            assert cfgmod.load_config()["models"]["formatter"]["groq_api_key"] == "gsk_user_value"

            os.environ.pop("GROQ_API_KEY")
            os.remove(path)
            assert cfgmod.load_config()["models"]["formatter"]["groq_api_key"] == ""
        finally:
            cfgmod.config_path = orig_path
            if orig_env is None:
                os.environ.pop("GROQ_API_KEY", None)
            else:
                os.environ["GROQ_API_KEY"] = orig_env


def test_device_listing_filters_virtual_and_duplicates():
    from src.audio.capture import list_input_devices

    devices = list_input_devices()
    names = [d.name.lower() for d in devices]
    assert len(names) == len(set(names)), "no duplicate endpoints across host APIs"
    assert all("stereo mix" not in n and "sound mapper" not in n for n in names)
    assert all(d.hostapi in ("Windows WASAPI", "MME", "Windows DirectSound") for d in devices)



def test_device_name_matching_only_merges_mme_truncations():
    from src.audio.capture import _same_device

    assert _same_device("Headset (realme Buds Air7)", "headset (realme buds air7)")
    # Distinct short names that merely share a prefix are different microphones
    assert not _same_device("Microphone", "Microphone (USB Audio)")
    assert not _same_device("Microphone (Realtek(R) Audio)", "Microphone (Realtek(R) Audio) 2")
    # MME's 31-char truncation still collapses onto the full WASAPI name
    full = "Microphone Array (Lenovo FHD Webcam Audio)"
    assert _same_device(full[:31], full)


def test_rescan_devices_reopens_live_streams():
    from src.audio import capture as cap

    mgr = cap.AudioCaptureManager()
    try:
        assert cap.rescan_devices()
        if cap.list_input_devices():
            assert mgr._stream is not None and mgr._stream.active
        mgr._recording = True
        assert not cap.rescan_devices(), "never reset PortAudio mid-dictation"
        mgr._recording = False
    finally:
        mgr.shutdown()


# ---------------------------------------------------------------------- pipeline policy
def test_pipeline_dead_signal_policy():
    """First silent capture warns only; a second consecutive one rotates the microphone."""
    from src.core import pipeline as pl

    class FakeCapture:
        target_sample_rate = 48000
        device_name = "Dead Mic"
        last_peak = 0.0
        rotations = 0
        device_spec = None

        def handle_dead_signal(self):
            self.rotations += 1
            return "Good Mic"

    class FakeHud:
        notices = []

        def show_notice(self, text):
            self.notices.append(text)

    p = pl.TaktPipeline.__new__(pl.TaktPipeline)
    p.capture, p.hud, p.hud_enabled, p._consecutive_dead = FakeCapture(), FakeHud(), True, 0
    p._handle_dead_signal(2.0)
    assert p.capture.rotations == 0 and p._consecutive_dead == 1
    p._handle_dead_signal(2.0)
    assert p.capture.rotations == 1 and p._consecutive_dead == 0
    assert len(p.hud.notices) == 2


# --------------------------------------------------------------------------------- state
def test_state_manager_transitions():
    from src.core.state import AppState, StateManager

    s = StateManager()
    seen = []
    s.add_listener(lambda a, b: seen.append((a, b)))
    assert s.transition_to(AppState.RECORDING) and not s.transition_to(AppState.RECORDING)
    assert seen == [(AppState.IDLE, AppState.RECORDING)]


# ----------------------------------------------------------------------------------- HUD
def test_hud_capsule_rim_is_symmetric_at_all_scales():
    import subprocess

    r = subprocess.run([sys.executable, os.path.join(PROJECT_ROOT, "scripts", "hud_render_test.py")],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"[PASS] {name}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"[FAIL] {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
