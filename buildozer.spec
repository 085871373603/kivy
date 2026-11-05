[app]
title = Stock Opname
package.name = stockopname
package.domain = org.stockopname
source.dir = .
source.include_exts = py
source.exclude_patterns = test_*.py, tests/*, tools/*, data/*
version = 1.0.0

# Python murni + pustaka pemilih/pengirim berkas Android. Tanpa pandas/numpy/Pillow
# (paket berbasis C butuh recipe khusus dan rawan gagal di Android).
# openssl + certifi: HTTPS ke Firebase (Android tidak punya daftar sertifikat CA bawaan).
requirements = python3,kivy==2.3.0,openssl,certifi,androidstorage4kivy,pyjnius,android

orientation = all
fullscreen = 0

# INTERNET: sinkronisasi Firebase. WRITE_EXTERNAL_STORAGE: hanya berlaku di Android 9 ke bawah
# (menyalin PNG ke Pictures sebelum dikirim ke WhatsApp); di Android 10+ tidak diperlukan.
android.permissions = INTERNET, WRITE_EXTERNAL_STORAGE

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
