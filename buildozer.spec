[app]
title = Excel Vault
package.name = excelvault
package.domain = org.excelvault
source.dir = .
source.include_exts = py
source.exclude_patterns = test_*.py, tests/*, storage/*
version = 1.0.0

# Hanya paket Python murni + pustaka pemilih file Android. Tanpa pandas/numpy
# (paket berbasis C butuh recipe khusus dan rawan gagal di Android).
requirements = python3,kivy==2.3.0,openpyxl,et_xmlfile,xlrd,androidstorage4kivy,pyjnius,android

orientation = all
fullscreen = 0

# Tidak butuh izin storage: file dipilih lewat Storage Access Framework (pemilih
# file bawaan Android) dan data disimpan di penyimpanan privat aplikasi.
android.permissions =

android.api = 33
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.release_artifact = apk

# Alat build DIKUNCI ke rilis lama yang stabil. Jangan ubah ke 'master'/'develop':
# python-for-android 2026 gagal ('No matching distribution found for pyjnius==1.7.0',
# issue kivy/python-for-android #3342) dan beralih ke Python 3.14.
android.ndk = 25b
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
