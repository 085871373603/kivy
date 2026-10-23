# Excel Vault

Aplikasi Kivy untuk menyimpan dan mencari data Excel/spreadsheet (`.xlsx`, `.xlsm`, `.xls`, `.ods`, `.csv`).
Berjalan di Android (APK dibangun otomatis oleh GitHub) dan di komputer.

**Cara kerja:** Upload → Tambah File → Simpan → Konfirmasi. Di Dashboard, ketik teks untuk mencari di dalam sel.
Setiap hasil menampilkan **sel** yang cocok beserta **seluruh baris** dari sel itu. Tombol **Clear** memulai pencarian baru.

| Berkas | Fungsi |
|---|---|
| `main.py` | Seluruh aplikasi |
| `test_main.py` | 83 uji otomatis (jalan di GitHub sebelum APK dibangun) |
| `buildozer.spec` | Konfigurasi APK Android |
| `.github/workflows/build-apk.yml` | Robot GitHub: uji, bangun APK, lampirkan ke Release |
| `requirements.txt` | Dependensi untuk menjalankan di komputer |

---

## Instalasi di Android lewat GitHub (alur lengkap)

```
Kode di GitHub ─► GitHub Actions (uji + bangun APK) ─► Release ─► unduh di HP ─► instal
```

Kebutuhan: akun GitHub (gratis) dan HP Android 7.0 ke atas. Tidak perlu Android Studio atau Linux.

### Langkah 1 — Buat repository
1. Masuk ke github.com, tekan **+** di kanan atas, pilih **New repository**.
2. Nama: `excel-vault`. Pilih **Public** (agar APK bisa diunduh di HP tanpa login), lalu **Create repository**.

### Langkah 2 — Siapkan kunci tanda tangan (disarankan, lakukan sekarang)
Android hanya mau **memperbarui** aplikasi jika tanda tangannya sama dengan versi terpasang. Tanpa kunci tetap,
setiap build memakai kunci acak, sehingga pembaruan ditolak ("App not installed") dan Anda harus menghapus
aplikasi dulu, yang **menghapus datanya**. Buat kunci sekali saja (perlu JDK, yang menyediakan `keytool`):

```
keytool -genkeypair -v -keystore excelvault.keystore -alias excelvault -keyalg RSA -keysize 2048 -validity 10000
```
Gunakan satu kata sandi untuk keystore dan kunci. Ubah ke teks base64:
- Linux: `base64 -w0 excelvault.keystore`
- macOS: `base64 -i excelvault.keystore`
- Windows PowerShell: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("excelvault.keystore"))`

Di repository: **Settings → Secrets and variables → Actions → New repository secret**, buat empat secret:

| Nama | Isi |
|---|---|
| `KEYSTORE_BASE64` | hasil base64 di atas |
| `KEYSTORE_PASSWORD` | kata sandi yang Anda pilih |
| `KEY_ALIAS` | `excelvault` |
| `KEY_PASSWORD` | kata sandi yang sama |

**Simpan berkas `excelvault.keystore` dan kata sandinya di tempat aman. Jika hilang, pembaruan tidak bisa lagi menimpa aplikasi lama.**
Jangan pernah mengunggah keystore ke repository (sudah dikecualikan di `.gitignore`).

### Langkah 3 — Unggah kode
**Opsi A (git):**
```
cd excel-vault
git init && git add . && git commit -m "Excel Vault"
git branch -M main
git remote add origin https://github.com/<username>/excel-vault.git
git push -u origin main
```
**Opsi B (lewat browser):** ekstrak ZIP, buka repository, **Add file → Upload files**, seret **isi** folder (termasuk folder
tersembunyi `.github`; di macOS tekan Cmd+Shift+. di Finder agar terlihat), lalu **Commit changes**.
Jika folder `.github` tidak ikut terunggah: **Add file → Create new file**, ketik nama `.github/workflows/build-apk.yml`
(garis miring otomatis membuat folder), tempel isi berkas itu, lalu Commit.

### Langkah 4 — Pastikan uji otomatis hijau
Buka tab **Actions**. Workflow **Build Android APK** menjalankan job **Uji otomatis** (sekitar 1 menit).
Tanda centang hijau berarti kode sehat. APK belum dibangun pada tahap ini, hanya diuji.

### Langkah 5 — Terbitkan Release (ini memicu pembuatan APK)
1. Buka **Releases → Draft a new release**.
2. **Choose a tag**: ketik `v1.0.0` lalu pilih **Create new tag: v1.0.0 on publish**.
3. Isi judul, misalnya `Excel Vault 1.0.0`, lalu **Publish release**.
4. Buka tab **Actions**: job **Bangun APK** berjalan. Build pertama memakan **30 sampai 60 menit** (mengunduh Android SDK/NDK dan
   mengompilasi untuk dua jenis CPU). Build berikutnya jauh lebih cepat berkat cache.
5. Setelah hijau, muat ulang halaman Release: berkas **`ExcelVault-v1.0.0.apk`** muncul di **Assets**.

Alternatif tanpa Release: **Actions → Build Android APK → Run workflow**, lalu unduh artefak `ExcelVault-apk`
dari halaman run tersebut (berbentuk ZIP dan butuh login GitHub).

### Langkah 6 — Instal di HP
1. Di HP, buka halaman Release repository Anda lewat Chrome, lalu ketuk **ExcelVault-v1.0.0.apk**. Jika muncul peringatan
   "berkas jenis ini dapat membahayakan perangkat", pilih **Download anyway**. Itu peringatan umum untuk semua APK di luar Play Store.
2. Buka berkas setelah selesai diunduh. Android akan meminta izin: **Settings → Install unknown apps → Chrome → Allow**
   (Android 7: aktifkan **Unknown sources**). Kembali, lalu ketuk **Install**.
3. Jika Play Protect menampilkan "Unrecognized developer" atau "Blocked by Play Protect": pilih **More details → Install anyway**.
   Itu wajar karena aplikasi ini tidak dipublikasikan di Play Store.
4. Ketuk **Open**.

### Langkah 7 — Pakai
1. **Upload → + Tambah File**: pemilih file bawaan Android terbuka (Downloads, Drive, penyimpanan internal, kartu SD). Pilih satu atau beberapa file.
2. **Simpan → Ya, simpan** → **Buka Dashboard**.
3. Ketik di kolom cari: hasil muncul langsung. **Clear** untuk mencari yang baru.
4. Tombol **Kembali** di Android: dari Upload kembali ke Dashboard.

---

## Akses penyimpanan dan penyimpanan lokal
- **Membaca file:** memakai *Storage Access Framework* (pemilih file sistem). Cara ini resmi untuk Android 5 sampai terbaru dan
  **tidak meminta izin penyimpanan**. Aplikasi hanya melihat file yang Anda pilih.
- **Menyimpan data:** file yang di-upload disalin ke penyimpanan privat aplikasi (`user_data_dir/storage`) beserta indeksnya.
  Data **tetap ada** setelah aplikasi ditutup atau HP dihidupkan ulang, dan bekerja tanpa internet. Data hilang jika aplikasi
  di-uninstall atau **Clear data** dipilih di pengaturan Android.
- Di komputer lokasinya: Linux `~/.config/excelvault`, Windows `%APPDATA%\excelvault`, macOS `~/Library/Application Support/excelvault`.

## Memperbarui aplikasi
Ubah kode, commit, lalu buat Release baru (`v1.0.1`, dan seterusnya). Naikkan juga `version` di `buildozer.spec`.
Unduh APK baru dan instal **di atas** yang lama. Data tetap aman jika Anda memakai kunci dari Langkah 2.

## Menjalankan di komputer dan pengujian
```
pip install -r requirements.txt
python main.py

pip install pytest openpyxl pyyaml
pytest -v test_main.py
```
Pengujian memakai Kivy tiruan, jadi tidak membuka jendela dan bisa berjalan di server (itu yang dilakukan GitHub Actions).

## Pemecahan masalah
| Gejala | Penyebab dan solusi |
|---|---|
| Job **Bangun APK** merah | Buka run tersebut → langkah **Bangun APK** → salin sekitar 40 baris terakhir log dan kirim ke pengembang. |
| "App not installed" saat memperbarui | Tanda tangan berbeda (Langkah 2 dilewati). Pilih uninstall (data hilang) lalu instal ulang, dan siapkan kunci tetap agar tidak terulang. |
| File tidak terlihat di pemilih file | Ketuk menu ☰ di pojok pemilih, lalu pilih sumber (Downloads, Drive, Dokumen). |
| "Sebagian file dilewati" | Formatnya bukan xlsx, xls, ods, atau csv, atau file rusak/kosong. |
| Angka/tanggal tampil berbeda dari Excel | Aplikasi menampilkan nilai mentah sel. Tanggal tampil seperti `2024-01-15 00:00:00`. |
| Baris pertama tidak ikut dicari | Itu disengaja: baris pertama berisi data dianggap judul kolom. |
