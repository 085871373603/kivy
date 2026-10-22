[app]
title = Excel Vault
package.name = excelvault
package.domain = id.my.arinex
source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,atlas,json
source.exclude_dirs = .git,.github,.pytest_cache,__pycache__,bin,storage,tests
source.exclude_patterns = test_*.py,*.pyc,*.pyo,*.zip,README.md,requirements.txt
version = 1.0.0

# Kivy + Android; documents are opened through Android's system document picker.
# NumPy requires Android minapi and NDK API >= 24; keep these values aligned.
# Avoid READ_EXTERNAL_STORAGE / MANAGE_EXTERNAL_STORAGE: scoped storage is respected.
requirements = python3,kivy,pandas,numpy,openpyxl,xlrd,odfpy,pyjnius
orientation = portrait
fullscreen = 0

android.api = 35
android.minapi = 24
android.ndk_api = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.allow_backup = True

# python-for-android's current development branch includes updated native recipes
# for pandas / numpy. GitHub Actions compiles the APK on a Linux runner.
p4a.branch = develop
p4a.bootstrap = sdl2

[buildozer]
log_level = 2
warn_on_root = 1
