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
# Data layer uses openpyxl/xlrd/odfpy; pandas and NumPy are intentionally not required.
# Avoid READ_EXTERNAL_STORAGE / MANAGE_EXTERNAL_STORAGE: scoped storage is respected.
requirements = python3,kivy,openpyxl,xlrd,odfpy,pyjnius
orientation = portrait
fullscreen = 0

android.api = 35
android.minapi = 24
android.ndk_api = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True

# Use the maintained python-for-android development recipe set.
p4a.branch = develop
p4a.bootstrap = sdl2

[buildozer]
log_level = 2
warn_on_root = 1
