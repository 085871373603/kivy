# Laporan Pengujian — Excel Vault

## Pengujian setelah pengurangan dependensi native

Lapisan data telah diubah agar tidak memakai `pandas` atau `numpy`. File CSV dibaca dengan modul standar Python; XLSX/XLSM dengan `openpyxl`; XLS dengan `xlrd`; ODS dengan `odfpy`. Struktur antarmuka dan alur upload → simpan → dashboard → pencarian tetap dipertahankan.

Perintah yang dijalankan di lingkungan Linux:

```text
python -m py_compile main.py vault_core.py test_main.py
python -m pytest -v test_main.py
```

Hasil terbaru: **7 passed, 0 failed**.

Cakupan tes:

1. Deteksi delimiter CSV dan pengecualian judul kolom dari pencarian.
2. Pembacaan workbook XLSX multi-sheet dan posisi baris/sel Excel.
3. Pembacaan ODS dan pencarian isi sel.
4. Penghitungan semua hasil meskipun tampilan hasil dibatasi.
5. Penyalinan workbook ke storage lokal dan pemuatan ulang indeks/file setelah cache dikosongkan.
6. Penolakan ekstensi yang tidak didukung dan spreadsheet kosong.
7. Migrasi direktori storage lama ke direktori data aplikasi yang baru.

## Batas verifikasi

Kivy dan Android SDK tidak tersedia di lingkungan ini. Paket `xlrd` juga tidak tersedia di runtime lokal saat tes dijalankan, sehingga format `.xls` belum diuji langsung di sini; workflow CI memasang `xlrd` sebelum pengujian. Pengujian ini membuktikan lapisan data CSV/XLSX/ODS dan sintaks Python, bukan keberhasilan build APK atau uji pemilih dokumen pada perangkat fisik. Build APK harus diverifikasi melalui GitHub Actions, lalu diuji pada perangkat Android.

## Perubahan untuk mengatasi kegagalan build

Log yang dibagikan sebelumnya hanya memperlihatkan ringkasan `pythonforandroid.toolchain create` gagal; penyebab pertama sebelum ringkasan tidak disertakan. Untuk mengurangi kemungkinan kegagalan recipe native, dependensi `pandas` dan `numpy` dihapus dan fungsi baca/cari ditulis ulang memakai list Python. Build Android saat ini menargetkan `arm64-v8a` saja untuk mengurangi waktu build dan risiko recipe lintas arsitektur. Workflow mencetak baris error yang relevan dan mengunggah `buildozer.log` sebagai artifact meskipun build gagal. Perubahan ini belum dianggap sebagai bukti bahwa build APK berhasil sebelum GitHub Actions selesai hijau.
