import os
import shutil
import subprocess
import time

dist_takt = r"C:\Users\Raghav\OpenFlow\dist\Takt"

# 1. Sync config
src_config = r"C:\Users\Raghav\OpenFlow\config"
dst_config = os.path.join(dist_takt, "config")
# Preserve any customized app_config.yaml already in dist (never destroy user settings).
dst_user_cfg = os.path.join(dst_config, "app_config.yaml")
preserved = None
if os.path.exists(dst_user_cfg):
    with open(dst_user_cfg, "rb") as f:
        preserved = f.read()
    backup = os.path.join(os.path.dirname(dist_takt), f"app_config.yaml.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(dst_user_cfg, backup)
    print(f"Backed up existing dist config to {backup}")
if os.path.exists(dst_config):
    shutil.rmtree(dst_config)
shutil.copytree(src_config, dst_config)
if preserved is not None:
    with open(dst_user_cfg, "wb") as f:
        f.write(preserved)
    print("Restored existing dist/Takt/config/app_config.yaml (user settings preserved)")
print("Synced config to dist/Takt/config")

# 2. Sync docs
shutil.copy2(r"C:\Users\Raghav\OpenFlow\SYSTEM_REQUIREMENTS.md", os.path.join(dist_takt, "SYSTEM_REQUIREMENTS.md"))
print("Synced SYSTEM_REQUIREMENTS.md")

# 3. Check C# companion executables
csc = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
ref_zip = "/reference:System.IO.Compression.FileSystem.dll,System.IO.Compression.dll"

for script, exe, refs in [
    (r"scripts\TaktSettingsLauncher.cs", "TaktSettings.exe", []),
    (r"scripts\TaktUpdate.cs", "TaktUpdate.exe", ["/reference:System.IO.Compression.FileSystem.dll", "/reference:System.IO.Compression.dll"]),
    (r"scripts\Uninstall.cs", "Uninstall.exe", [])
]:
    out_exe = os.path.join(dist_takt, exe)
    cmd = [csc, "/nologo", "/target:winexe", f"/out:{out_exe}"] + refs + [script]
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(f"Compiled {exe} -> code {res.returncode}")
    if res.returncode != 0:
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)

# 4. Recompile TaktSetup.exe (version stamped from the latest git tag)
subprocess.run(["python", r"scripts\write_build_info.py"], check=True)
setup_exe = r"C:\Users\Raghav\OpenFlow\dist\TaktSetup.exe"
cmd_setup = [csc, "/nologo", "/target:winexe", f"/out:{setup_exe}", "/reference:System.IO.Compression.FileSystem.dll", "/reference:System.IO.Compression.dll", r"scripts\TaktSetup.cs", r"scripts\BuildInfo.g.cs"]
res_setup = subprocess.run(cmd_setup, capture_output=True, text=True)
print(f"Compiled TaktSetup.exe -> code {res_setup.returncode}")
if res_setup.returncode != 0:
    print("STDOUT:", res_setup.stdout)
    print("STDERR:", res_setup.stderr)
