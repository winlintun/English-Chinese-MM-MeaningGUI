"""Android entry point — pyside6-android-deploy requires a main.py.

Desktop users run vocapp.py directly; this file only matters for the
Android build, where the packaged app directory is read-only, so the
writable app-data location (ANDROID_PRIVATE, set by python-for-android)
must be found first and the bundled fonts + starter database seeded into
it on first launch.

The startup log is written to <app files>/vocapp-startup.log and echoed to
stderr (logcat tag "python"). If Qt can be imported, a startup failure also
shows an error dialog with the traceback copied to the clipboard."""
import os
import shutil
import sys
import time
import traceback


# python-for-android exports ANDROID_PRIVATE = the app's private files dir
# (writable) and ANDROID_ARGUMENT/ANDROID_APP_PATH = the unpacked app dir.
ANDROID_PRIVATE = os.environ.get("ANDROID_PRIVATE", "")
IS_ANDROID = bool(
    ANDROID_PRIVATE
    or os.environ.get("ANDROID_ARGUMENT")
    or os.environ.get("P4A_BOOTSTRAP")
)


def _log(message):
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message)
    try:
        print(line, file=sys.stderr, flush=True)
    except Exception:
        pass
    if not ANDROID_PRIVATE:
        return
    try:
        with open(os.path.join(ANDROID_PRIVATE, "vocapp-startup.log"),
                  "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


def _show_startup_error(text):
    """Best-effort on-screen report; needs only PySide6 itself."""
    try:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        QGuiApplication.clipboard().setText(text)
        box = QMessageBox()
        box.setWindowTitle("VocApp startup error")
        box.setIcon(QMessageBox.Icon.Critical)
        box.setText(
            "VocApp could not start.\n\n"
            "The details were copied to the clipboard — please send them "
            "to the developer."
        )
        box.setDetailedText(text)
        box.exec()
    except Exception:
        _log("could not show error dialog:\n" + traceback.format_exc())


def _bundled_dir():
    """Directory holding the packaged assets (fonts/, vocabulary.db)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (here, os.environ.get("ANDROID_APP_PATH", "")):
        if candidate and os.path.isdir(os.path.join(candidate, "fonts")):
            return candidate
    return here


def _writable_data_dir():
    if ANDROID_PRIVATE:
        # getFilesDir(): always writable, and avoids touching QStandardPaths
        # before a QApplication exists (which is fragile on Android).
        os.makedirs(ANDROID_PRIVATE, exist_ok=True)
        return ANDROID_PRIVATE
    from PySide6.QtCore import QCoreApplication, QStandardPaths
    QCoreApplication.setApplicationName("VocApp")
    QCoreApplication.setOrganizationName("VocApp")
    locations = QStandardPaths.standardLocations(
        QStandardPaths.StandardLocation.AppDataLocation)
    if locations:
        os.makedirs(locations[0], exist_ok=True)
        return locations[0]
    return os.getcwd()


def _seed_data_dir():
    bundled = _bundled_dir()
    data = _writable_data_dir()
    _log("startup: android=%s bundled=%s data=%s"
         % (IS_ANDROID, bundled, data))
    fonts_src = os.path.join(bundled, "fonts")
    fonts_dst = os.path.join(data, "fonts")
    if os.path.isdir(fonts_src) and not os.path.isdir(fonts_dst):
        _log("startup: copying bundled fonts")
        shutil.copytree(fonts_src, fonts_dst)
    if not os.path.exists(os.path.join(data, "vocabulary.db")):
        _log("startup: seeding database")
        for seed in ("vocabulary.db", "vocabulary_seed.db"):
            src = os.path.join(bundled, seed)
            if os.path.isfile(src):
                shutil.copy(src, os.path.join(data, "vocabulary.db"))
                break
    _log("startup: database=%s (%s bytes)" % (
        os.path.exists(os.path.join(data, "vocabulary.db")),
        os.path.getsize(os.path.join(data, "vocabulary.db"))
        if os.path.exists(os.path.join(data, "vocabulary.db")) else 0,
    ))
    os.environ["VOCAPP_DATA_DIR"] = data
    return data


_log("startup: main.py pid=%s python=%s" % (os.getpid(), sys.version.split()[0]))

if IS_ANDROID:
    try:
        _seed_data_dir()
    except Exception:
        text = traceback.format_exc()
        _log("startup: seeding failed:\n" + text)
        _show_startup_error(text)
        raise

try:
    _log("startup: importing vocapp")
    import vocapp
    _log("startup: vocapp imported")
except Exception:
    text = traceback.format_exc()
    _log("startup: importing vocapp failed:\n" + text)
    _show_startup_error(text)
    raise

if __name__ in ("__main__", "__mp_main__") or IS_ANDROID:
    try:
        _log("startup: calling vocapp.main()")
        vocapp.main()
    except SystemExit:
        _log("startup: vocapp.main() exited")
        raise
    except Exception:
        text = traceback.format_exc()
        _log("startup: vocapp.main() failed:\n" + text)
        if IS_ANDROID:
            _show_startup_error(text)
        raise
