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
requirements = python3,kivy==2.3.1,openpyxl,et_xmlfile,xlrd,androidstorage4kivy,pyjnius,android

orientation = all
fullscreen = 0

# Tidak butuh izin storage: file dipilih lewat Storage Access Framework (pemilih
# file bawaan Android) dan data disimpan di penyimpanan privat aplikasi.
android.permissions =

android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.release_artifact = apk
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
