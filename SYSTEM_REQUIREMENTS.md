# Takt — System Requirements & Expected Performance

Takt is an ultra-fast, 100% private local voice dictation application for Windows. All audio capture, noise cancellation, transcription, and text formatting occur entirely on-device. Your voice and data never touch external cloud servers.

---

## 1. System Requirements

### Minimum Requirements (CPU-Only Mode)
*Suitable for modern laptops and desktops without dedicated NVIDIA graphics.*

| Component | Specification |
| :--- | :--- |
| **Operating System** | Windows 10 (64-bit, Version 20H2 or later) or Windows 11 (64-bit) |
| **Processor (CPU)** | Intel Core i5 (8th Gen or newer) / AMD Ryzen 3 or 5 (3000 series or newer) <br> *(4 physical cores minimum)* |
| **System Memory (RAM)** | 8 GB RAM |
| **Storage Space** | 1.5 GB free disk space (SSD strongly recommended) |
| **Audio Input** | Any standard microphone (laptop built-in, USB headset, 3.5mm, or Bluetooth) |
| **Permissions** | Standard user permissions (No Administrator / UAC prompt required) |

---

### Recommended Requirements (GPU-Accelerated Mode)
*Delivers near-instantaneous transcription with RTX GPU acceleration.*

| Component | Specification |
| :--- | :--- |
| **Operating System** | Windows 11 (64-bit) |
| **Processor (CPU)** | Intel Core i7 (10th Gen or newer) / AMD Ryzen 7 (5000 series or newer) |
| **System Memory (RAM)** | 16 GB RAM or higher |
| **Graphics (GPU)** | NVIDIA GeForce RTX 3050, 3060, 4060 or higher (DirectML / CUDA compatible) |
| **Storage Space** | 2.0 GB free NVMe SSD space |
| **Audio Input** | Quality USB microphone or noise-cancelling headset |

---

## 2. Expected Performance Benchmarks

| Metric | Minimum Specs (CPU INT8) | Recommended Specs (RTX GPU) |
| :--- | :--- | :--- |
| **Resting Memory Footprint** | ~72 MB RAM | ~72 MB RAM |
| **Idle CPU Utilization** | **0.0%** *(Timer hibernates when HUD is hidden)* | **0.0%** |
| **Peak Memory During Speech** | ~800 MB – 1.4 GB RAM | ~1.2 GB RAM (VRAM: ~1.5 GB) |
| **Transcription Latency** *(for 5s speech)* | **0.6s – 1.1s** | **0.15s – 0.30s** *(Near-instant)* |
| **Real-Time Factor (RTF)** | ~0.15x – 0.20x | **0.03x – 0.05x** |
| **Text Injection Latency** | **0 ms** *(Atomic direct Unicode injection)* | **0 ms** |
| **Visualizer Frame Rate** | 60 FPS hardware-accelerated | 60 FPS hardware-accelerated |

---

## 3. How to Update Takt (For You & Friends)

### Method A: Direct In-App Update (1-Click)
1. Double-click the Takt tray icon to open **Preferences & Settings**.
2. Scroll to the **App Updates** section.
3. Click **Check for Updates** or **Install Update Package (.zip)...**.
4. Takt will apply the update, preserve all your personal hotkeys and configs, and restart automatically.

### Method B: Standalone Update Patch (`TaktUpdate.exe`)
1. Download or receive `TaktUpdate.zip` from Raghav.
2. Run `TaktUpdate.exe`.
3. The updater cleanly closes any running Takt instance, updates core binaries and models, and boots the new version.

---

## 4. Performance & Tuning Tips

- **Hotkey Customization**: The default push-to-talk key is `Right Alt` (`alt_r`), which never interferes with normal typing. You can change this to `F8`, `F9`, or toggle mode anytime in Settings.
- **Microphone Selection**: If you have multiple microphones (e.g., webcam vs dedicated headset), select your primary mic in Settings to avoid room echo.
- **Privacy Shield**: Enable the Desert Ant Labs 'Redact' toggle in Settings if you work with sensitive tokens, credit cards, or API keys.
