"""Android entry point — pyside6-android-deploy requires a main.py.

Desktop users run vocapp.py directly; this file only matters for the
Android build, where the packaged app directory is read-only, so the
writable app-data location (QStandardPaths) must be found first and the
bundled fonts + starter database seeded into it on first launch."""
import os
import shutil


IS_ANDROID = bool(os.environ.get("ANDROID_ROOT"))


def _bundled_dir():
    """Directory holding the packaged assets (fonts/, vocabulary.db)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (here, os.environ.get("ANDROID_APP_PATH", "")):
        if candidate and os.path.isdir(os.path.join(candidate, "fonts")):
            return candidate
    return here


def _writable_data_dir():
    from PySide6.QtCore import QCoreApplication, QStandardPaths
    QCoreApplication.setApplicationName("VocApp")
    QCoreApplication.setOrganizationName("VocApp")
    locations = QStandardPaths.standardLocations(
        QStandardPaths.StandardLocation.AppDataLocation)
    if locations:
        os.makedirs(locations[0], exist_ok=True)
        return locations[0]
    return os.getcwd()


if IS_ANDROID:
    bundled = _bundled_dir()
    data = _writable_data_dir()
    fonts_src = os.path.join(bundled, "fonts")
    fonts_dst = os.path.join(data, "fonts")
    if os.path.isdir(fonts_src) and not os.path.isdir(fonts_dst):
        shutil.copytree(fonts_src, fonts_dst)
    if not os.path.exists(os.path.join(data, "vocabulary.db")):
        for seed in ("vocabulary.db", "vocabulary_seed.db"):
            src = os.path.join(bundled, seed)
            if os.path.isfile(src):
                shutil.copy(src, os.path.join(data, "vocabulary.db"))
                break
    os.environ["VOCAPP_DATA_DIR"] = data

import vocapp

if __name__ in ("__main__", "__mp_main__") or IS_ANDROID:
    vocapp.main()
