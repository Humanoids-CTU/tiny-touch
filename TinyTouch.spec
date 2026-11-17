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

# Executable icon: the same "TT" logo the windows use (gui/app_icon.py),
# rendered into the build folder so no .ico file has to be kept in the repo.
# Windows only; Linux executables carry no embedded icon.
exe_icon = None
if sys.platform == "win32":
    sys.path.insert(0, src_root)
    from gui.app_icon import ICON_SIZES, render_icon

    exe_icon = os.path.join(workpath, "TinyTouch.ico")
    os.makedirs(workpath, exist_ok=True)
    icon_images = [render_icon(size) for size in ICON_SIZES]
    icon_images[-1].save(
        exe_icon,
        format="ICO",
        sizes=[(size, size) for size in ICON_SIZES],
        append_images=icon_images[:-1],
    )

# Bootloader splash: shown the moment the .exe starts, while the onefile
# bundle unpacks. src/startup_splash.py animates the status line and closes it
# once the main window is shown. text_pos is the bottom-left of the status text.
splash = Splash(
    os.path.join(project_root, "assets", "splash.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(32, 244),
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
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
