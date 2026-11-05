# Stock Opname

Aplikasi Android/desktop (Kivy) untuk stock opname. **Berjalan tanpa database** (data tersimpan lokal di perangkat)
dan **bisa disinkronkan ke Firebase Realtime Database** bila Anda mau. Hasil akhir dikirim ke **WhatsApp sebagai gambar PNG**.

## Alur

**Beranda**
- **GENERAL**
  - **Input SKU**: input dan simpan data produk (PLU, deskripsi, OH = stok sistem). Ketuk produk di daftar untuk mengubah atau menghapus.
  - **Setting Item Stock Opname**: pilih produk yang harus di-SO, lalu **Simpan Setup** dan konfirmasi.
- **STOCK OPNAME**: dashboard kerja berbentuk tabel sel.
- **Firebase (opsional)**: pengaturan sinkronisasi.

**Tabel Stock Opname**

| PLU / Deskripsi | OH | 1 | 2 | 3 | 4 | 5 | Total Fisik | Selisih |
|---|---|---|---|---|---|---|---|---|

- **Total Fisik** = kolom 1 + 2 + 3 + 4 + 5, dan **Selisih** = Total Fisik - OH. Keduanya dihitung otomatis.
- Ketuk sel hitungan (atau barisnya): muncul editor 5 kolom dengan Total Fisik dan Selisih langsung. **Simpan & Berikutnya** untuk lanjut cepat.
- Isi **0** bila memang tidak ada stok. Kolom kosong berarti belum dihitung. Satu produk dianggap selesai bila minimal satu kolom terisi.
- Baris berwarna: hijau = sesuai, merah = kurang, oranye = lebih. Tabel bisa digeser ke samping dan dicari lewat kolom cari.
- Setelah **semua** produk dihitung: **Simpan & Konfirmasi** menampilkan ringkasan. Setelah dikonfirmasi, hasil dikunci (final) dan
  **gambar PNG langsung dikirim ke WhatsApp**. **Kirim WA** mengirim ulang, **Revisi** membuka kembali sesi final.
- OH pada sesi adalah salinan saat setup disimpan. Menyimpan setup lagi memperbarui OH dari data produk dan mempertahankan hitungan yang sudah ada.

## Pasang di Android lewat GitHub

Sama seperti Excel Vault yang sudah berhasil di lingkungan Anda:

1. Buat repository baru (disarankan terpisah, misalnya `stock-opname`), lalu unggah **seluruh isi** ZIP, termasuk folder tersembunyi `.github`.
2. Tab **Actions**: pastikan job **Uji otomatis** hijau.
3. **Actions → Build Android APK → Run workflow → Run workflow**. Sekitar 30 sampai 45 menit, lalu APK muncul di **Releases** (pre-release `build-N`).
   Atau terbitkan Release dengan tag **huruf v kecil**, misalnya `v1.0.0`.
4. Unduh APK di HP, izinkan **Install unknown apps**, lalu pasang. Jika Play Protect memperingatkan, pilih **Install anyway**.
5. Untuk pembaruan di atas versi lama tanpa kehilangan data, siapkan kunci tanda tangan tetap (4 secret: `KEYSTORE_BASE64`,
   `KEYSTORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`) sebelum build versi final. Penjelasannya sama dengan README Excel Vault.

Jika build gagal, buka halaman **Summary** run tersebut: bagian *45 baris tepat sebelum kegagalan terakhir* menunjukkan penyebabnya.

## Firebase (opsional)

Tanpa Firebase, semua fitur tetap berjalan dan data hanya ada di perangkat. Untuk mengaktifkannya:

1. Di console.firebase.google.com buat proyek, lalu **Build → Realtime Database → Create database**.
2. Salin **URL database** (misalnya `https://nama-proyek-default-rtdb.asia-southeast1.firebasedatabase.app`).
3. Atur **Rules**. Aplikasi mengirim token lewat parameter `auth`:
   - **Uji coba singkat:** `{ "rules": { ".read": true, ".write": true } }`. **Berbahaya untuk data sungguhan**: siapa pun yang tahu URL bisa membaca dan menulis.
   - **Lebih aman:** batasi dengan `auth != null` dan isi kolom *Token* di aplikasi (ID token Firebase Auth, atau database secret lama).
     Catatan: ID token kedaluwarsa sekitar 1 jam, jadi untuk pemakaian rutin lebih cocok dibuatkan fitur login email/password
     (token bisa diperbarui otomatis). Itu belum termasuk di versi ini.
4. Di aplikasi: **Firebase (opsional)** lalu isi URL (dan token bila perlu), tekan **Simpan**, lalu **Tes koneksi**.
5. **Sinkron otomatis saat menyimpan** mengirim perubahan produk, setup, dan hasil final secara otomatis di latar belakang. Bila gagal, aplikasi tetap
   berjalan lokal dan statusnya tampil di Beranda. **Kirim semua** dan **Ambil dari Firebase** untuk sinkron manual (ambil = produk digabung, sesi aktif diganti).
6. **Path root** memisahkan data per toko, misalnya `toko/jakarta`.

Struktur data di Firebase: `<root>/products/<PLU>`, `<root>/sessions/<no-sesi>`, `<root>/meta/active_session`. Kunci PLU yang memuat karakter terlarang
Firebase (`. $ # [ ] /`) dikodekan otomatis dan dipulihkan saat diambil.

## Penyimpanan, izin, dan WhatsApp

- Data: folder data aplikasi (`user_data_dir/data`), berupa berkas JSON. Tetap ada setelah aplikasi ditutup, hilang bila aplikasi di-uninstall atau **Clear data**.
- Izin **INTERNET** dipakai hanya untuk Firebase. Izin tulis penyimpanan hanya berlaku di Android 9 ke bawah.
- Gambar dibuat dalam halaman (20 produk per gambar) agar tetap terbaca di WhatsApp, disalin ke galeri (folder Pictures), lalu dikirim lewat berbagi
  Android langsung ke WhatsApp. Jika WhatsApp tidak terpasang, muncul pilihan aplikasi. Di komputer, gambar disimpan di folder `data/exports`.

## Komputer dan pengujian

```
pip install -r requirements.txt
python main.py

pip install pytest pyyaml
pytest -v test_main.py
```
Pengujian memakai Kivy tiruan dan server Firebase palsu di jaringan lokal, jadi tidak butuh layar maupun internet.

## Pemecahan masalah

| Gejala | Solusi |
|---|---|
| Tes koneksi: "Akses ditolak" | Periksa Rules database dan token. |
| Tes koneksi: "Tidak dapat terhubung" | Periksa internet dan URL database. |
| WhatsApp tidak terbuka | Pastikan terpasang. Gambar tetap ada di galeri (Pictures) dan di data aplikasi. |
| Build gagal | Lihat halaman **Summary** run (ringkasan error otomatis). |
