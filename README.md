# Excel Vault — Android / Kivy

Aplikasi lokal untuk menyimpan dan mencari teks di dalam file Excel/spreadsheet. Versi ini mempertahankan alur utama: **Tambah File → antrean → Simpan → Dashboard → pencarian live → Clear**.

## Perubahan penting untuk Android

- **Pemilihan file memakai Android Storage Access Framework (SAF)** melalui pemilih dokumen bawaan. Pengguna memilih file secara eksplisit; aplikasi tidak meminta izin penyimpanan luas yang sudah dibatasi Android modern.
- File yang dipilih disalin ke folder sementara aplikasi. Sesudah tombol **Simpan**, file final dan `index.json` berada di `App.user_data_dir/storage/` yang dapat ditulis dan tetap ada saat aplikasi ditutup/dibuka ulang.
- Data disimpan lokal di perangkat, bukan di cloud. Menghapus cache aplikasi bukan cara untuk membersihkan data aplikasi; **menghapus aplikasi akan menghapus data lokal aplikasi**. Buat salinan file asal bila ingin menyimpan data di luar aplikasi.
- Mendukung `.xlsx`, `.xlsm`, `.xls`, `.ods`, dan `.csv` sesuai engine yang dipaketkan.
- Dashboard tetap mencari di isi sel, bukan judul kolom. Hasil menunjukkan sel yang cocok sekaligus semua nilai pada baris tersebut.
- Data layer dipisah dalam `vault_core.py` agar fungsi pembacaan, pencarian, dan penyimpanan bisa diuji tanpa menjalankan antarmuka Kivy.
- Lapisan data **tidak memakai `pandas` atau `numpy`**. Pembacaan dilakukan langsung melalui `openpyxl` (XLSX/XLSM), `xlrd` (XLS), `odfpy` (ODS), dan modul `csv` bawaan Python. Ini mengurangi komponen native yang harus dikompilasi ketika membuat APK.

## Struktur proyek

```text
excel_vault_android/
├── main.py
├── vault_core.py
├── test_main.py
├── requirements.txt
├── buildozer.spec
├── README.md
└── .github/workflows/android.yml
```

## Konfigurasi Android dan dependensi build

Konfigurasi saat ini menetapkan Android API target 35, minimum API 24, NDK API 24, dan arsitektur `arm64-v8a`. NumPy/pandas sudah dikeluarkan dari dependensi aplikasi agar build Android tidak perlu mengompilasi kedua pustaka tersebut. Karena hanya `arm64-v8a` yang dibangun, perangkat Android 32-bit saja tidak didukung oleh APK ini.

Jika GitHub Actions masih gagal, pesan `Buildozer failed to execute the last command` hanyalah ringkasan. Buka artifact `excel-vault-build-log` dan cari pesan `ERROR`, `Traceback`, `FAILED`, atau `fatal error` pertama yang muncul sebelumnya. Workflow terbaru juga mencetak ringkasan error ke log job.

## Pengujian otomatis

Python 3.11 direkomendasikan untuk tes lokal:

```bash
python -m pip install openpyxl xlrd odfpy pytest
python -m pytest -v test_main.py
```

Tes meliputi CSV delimiter titik koma, header yang tidak dicari, workbook XLSX multi-sheet, pencarian beberapa sel dalam baris, pembatasan hasil yang ditampilkan, persistensi file/index setelah cache dibersihkan, dan penolakan format tidak didukung/file kosong.

## Membuat APK dengan GitHub dari browser Android (tanpa Terminal)

### 1. Buat repository

1. Buka [GitHub](https://github.com/) dan masuk ke akun.
2. Tekan **+ → New repository**. Beri nama misalnya `excel-vault-android`, pilih **Public** (lebih mudah untuk akses hasil build) atau Private sesuai kebutuhan, lalu **Create repository**.
3. Ekstrak ZIP proyek ini di ponsel memakai aplikasi File Manager agar file sumber siap diunggah.

### 2. Unggah kode ke repository

GitHub Actions memerlukan semua berkas sumber dan file workflow. Lewat browser, sebaiknya aktifkan **Situs desktop** bila memakai Chrome Android.

1. Dari halaman repository, pilih **Add file → Upload files**.
2. Unggah `main.py`, `vault_core.py`, `test_main.py`, `requirements.txt`, `buildozer.spec`, `README.md`, dan `.gitignore`, lalu commit ke branch `main`.
3. Buat workflow dengan memilih **Add file → Create new file**. Untuk nama file, ketik tepat: `.github/workflows/android.yml`. Tempel isi file `android.yml` dari folder proyek, lalu commit.
4. Pastikan di repository terdapat path `.github/workflows/android.yml` (bukan `android.yml` di folder utama). Workflow akan menjalankan tes terlebih dahulu dan hanya membangun APK jika tes lulus. Workflow yang disediakan menjalankan Buildozer langsung di runner Ubuntu agar pesan kegagalan lebih lengkap daripada wrapper Docker.

> Catatan: jika uploader browser menyembunyikan folder `.github`, buat file workflow melalui **Create new file** seperti langkah 3.

### 3. Jalankan build APK

1. Buka tab **Actions** pada repository.
2. Pilih workflow **Test and build Excel Vault APK**. Jika tidak berjalan otomatis setelah commit, tekan **Run workflow**.
3. Buka proses terbaru. Tunggu sampai job `Python data tests` dan `Build Android APK` sama-sama berstatus hijau.
4. Pada bagian **Artifacts**, unduh `excel-vault-android-apk`. Unduhan artifact biasanya berupa ZIP; ekstrak ZIP tersebut sampai terlihat file berakhiran `.apk`.
5. Jika build gagal, tetap buka **Artifacts** dan unduh `excel-vault-build-log` untuk melihat log Buildozer terperinci. Cari pesan `ERROR`, `Traceback`, atau `FAILED` pertama yang muncul sebelum baris akhir `Build failed`.
6. Jika membuat tag GitHub yang diawali `v`, contohnya `v1.0.0`, workflow yang berhasil juga melampirkan APK ke halaman **Releases**.

GitHub Actions membangun APK di server GitHub; Anda tidak perlu memasang Android SDK, NDK, Buildozer, atau menjalankan perintah terminal di ponsel. Workflow menjalankan build secara langsung pada runner Ubuntu dan memasang dependensi sistem build (termasuk `autopoint`/`gettext`) untuk mengurangi kegagalan recipe native; ini belum menjamin build berhasil tanpa memeriksa log aktual.

## Memasang APK di Android

1. Unduh lalu ekstrak artifact APK di atas.
2. Ketuk file `excelvault-...debug.apk` dari aplikasi File Manager.
3. Android mungkin meminta izin **Install unknown apps / Izinkan dari sumber ini** untuk browser atau File Manager yang dipakai. Aktifkan hanya untuk sumber tepercaya tersebut, kembali ke installer, lalu tekan **Install**.
4. Buka **Excel Vault**. Tekan **+ Tambah File**, pilih file lewat pemilih dokumen Android, lalu tekan **Simpan** dan konfirmasi.
5. Masuk ke **Dashboard**, ketik kata kunci dalam sel. Tekan **Clear** untuk menghapus kueri.

APK debug ditujukan untuk penggunaan/pengujian pribadi. Untuk distribusi luas, buat build release yang ditandatangani dengan kunci sendiri dan jangan membagikan keystore atau kata sandinya.

## Di mana data disimpan?

Indeks disimpan sebagai `storage/index.json` dan salinan file berada di `storage/files/`, di bawah direktori data privat aplikasi. Lokasi fisik tepatnya ditentukan oleh Android/Kivy; direktori privat tidak dirancang untuk dibuka langsung melalui file manager biasa. File yang asli tidak dihapus oleh aplikasi.

## Batas verifikasi

Tes otomatis memverifikasi lapisan data di Linux, bukan antarmuka Kivy atau akses picker pada ponsel sungguhan. APK belum dianggap teruji pada perangkat sampai workflow GitHub selesai membangun paket dan APK tersebut dipasang serta dicoba pada Android. Uji perangkat yang disarankan: pilih file dari Downloads/Drive provider, simpan, tutup paksa lalu buka kembali, cari kata kunci, dan cek workbook dengan lebih dari satu sheet.
