# -*- mode: python ; coding: utf-8 -*-

import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

spec_path = os.path.abspath(sys.argv[0]) if sys.argv else os.path.abspath("TinyTouch.spec")
project_root = os.path.abspath(os.path.dirname(spec_path))
src_root = os.path.join(project_root, "src")

# Destinations MUST match gui/resource_utils:
#   resource_path("config.json")      -> <_MEIPASS>/config.json        (dest ".")
#   asset_path("icons/<...>")         -> <_MEIPASS>/resources/icons/…  (dest "resources")
datas = [
    (os.path.join(project_root, "config.json"), "."),
    (os.path.join(src_root, "resources"), "resources"),
]
datas += collect_data_files("ttkbootstrap")  # localization .msg files

a = Analysis(
    ["src/main.py"],
    pathex=[src_root],
    binaries=collect_dynamic_libs("sdl2dll", search_patterns=["*.dll", "*.dylib", "lib*.so*"]),
    datas=datas,
    hiddenimports=[
        "PIL._tkinter_finder",
        "PIL._tkinter",
        "sdl2dll",
        "sdl2",  # Loaded lazily so CPU mode also works without the GPU runtime.
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# Executable icon: the same hand logo the windows use (gui/app_icon.py),
# rendered into the build folder so no .ico file has to be kept in the repo.
# Windows only; Linux executables carry no embedded icon.
exe_icon = None
if sys.platform == "win32":
    sys.path.insert(0, src_root)
    from gui.app_icon import write_ico

    exe_icon = os.path.join(workpath, "TinyTouch.ico")
    os.makedirs(workpath, exist_ok=True)
    write_ico(exe_icon)

# Windows manifest: PyInstaller's default plus per-monitor DPI awareness from
# process start, so the splash is drawn at native resolution instead of being
# stretched (blurry) by Windows on scaled displays. "PerMonitor" matches what
# main.enable_dpi_awareness() requests for the app itself.
WINDOWS_MANIFEST = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false"></requestedExecutionLevel>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <supportedOS Id="{e2011457-1546-43c5-a5fe-008deee3d3f0}"></supportedOS>
      <supportedOS Id="{35138b9a-5d96-4fbd-8e2d-a2440225f93a}"></supportedOS>
      <supportedOS Id="{4a2f28e3-53b9-4441-ba9c-d69d4a4a6e38}"></supportedOS>
      <supportedOS Id="{1f676c76-80e1-4239-95bb-83d0f6d0da78}"></supportedOS>
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"></supportedOS>
    </application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitor</dpiAwareness>
    </windowsSettings>
  </application>
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls" version="6.0.0.0" processorArchitecture="*" publicKeyToken="6595b64144ccf1df" language="*"></assemblyIdentity>
    </dependentAssembly>
  </dependency>
</assembly>
"""

# Bootloader splash: shown the moment the .exe starts, while the onefile
# bundle unpacks. src/startup_splash.py animates the status line and closes it
# once the main window is shown. text_pos is the bottom-left of the status text.
splash = Splash(
    os.path.join(project_root, "assets", "splash.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(48, 366),
    text_size=10,
    text_color="#6e6e73",
    text_default="Starting",
    minify_script=True,
    always_on_top=False,
)

app_name = os.environ.get("TINYTOUCH_APP_NAME", "TinyTouch")

exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    a.binaries,
    a.datas,
    [],
    name=app_name,
    console=False,
    icon=exe_icon,
    manifest=WINDOWS_MANIFEST if sys.platform == "win32" else None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
