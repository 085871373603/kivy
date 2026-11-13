[app]
title = TIMER MAKDIS
package.name = timermakdis kivy
package.domain = org.timermaxdis
source.dir = .
source.include_exts = py
source.exclude_patterns = test_*.py, tests/*, tools/*, store/*
version = 1.0.0

# Python murni + pyjnius/android (layar tetap menyala, buka browser). Tanpa paket berbasis C.
requirements = python3,kivy==2.3.0,pyjnius,android

orientation = portrait
fullscreen = 0

# Tidak butuh izin apa pun: FLAG_KEEP_SCREEN_ON dan membuka browser tidak memerlukannya.
android.permissions =

android.api = 33
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.release_artifact = apk

# Alat build DIKUNCI ke rilis lama yang stabil (terbukti berhasil di lingkungan pengguna).
# Jangan ubah ke 'master'/'develop': python-for-android 2026 gagal
# ('No matching distribution found for pyjnius==1.7.0', issue kivy/python-for-android #3342).
android.ndk = 25b
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
