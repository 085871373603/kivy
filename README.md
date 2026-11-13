# TIMER MAXDIS (versi Kivy / APK)

Versi native dari `index.html` (PWA TIMER MAXDIS) milik Anda, dibuat dengan Kivy dan dibangun menjadi APK lewat GitHub Actions
(pipeline yang sama dengan Excel Vault dan Stock Opname yang sudah berhasil di lingkungan Anda).

## Seberapa sama dengan aslinya?

Logika inti **bukan ditulis ulang dari ingatan**: setiap fungsi di `logic.py` adalah port dari fungsi JavaScript aslinya, lalu **dibuktikan sama persis
dengan menjalankan kode JavaScript asli di Node.js**. `tools/reference.js` memuat salinan logika dari HTML Anda (hanya baris DOM yang dibuang),
`tools/gen_golden.js` menjalankannya pada ribuan input acak dan menyimpan jawabannya di `golden.json`, dan `test_main.py` memeriksa port Python terhadapnya:

| Yang dibandingkan | Jumlah vektor | Selisih |
|---|---|---|
| `formatDuration`, `getShift`, `formatDateTime`, `toLocaleString("id-ID")`, `toFixed(1)` | sekitar 2.800 | 0 |
| durasi timer `ceil((qty/12)*60)`, tampilan MM:SS, progres, pesan waktu | 1.400 | 0 |
| `evaluateTiming` (batas -10% dan +10%) dan posisi tooltip tutorial | 780 | 0 |
| sesi lengkap 6 lorong: hasil, status, dan isi penyimpanan di setiap langkah | 227 sesi | 0 |
| reset saat start (`processStartupReset`, semua kombinasi) | 420 | 0 |

Teks, warna, rumus, urutan lorong, batas shift, dan alur (Input, Proses, Selesai, popup hasil, alarm, tutorial) mengikuti HTML Anda.

**Keunikan kode asli yang dipertahankan:** karena floating point JavaScript, `(100/12)*60` bernilai 500,00000000000006, sehingga timer untuk qty 100
adalah 501 detik, bukan 500. Ini terjadi pada 14 dari 400 qty bulat pertama (misalnya 25, 50, 97, 100, 194, 197, 200). Saya tidak mengubahnya,
sesuai permintaan "jangan ubah apa pun". Jika ingin dibulatkan secara matematis, itu perubahan satu baris di `logic.py` dan di HTML aslinya.

## Server dan tombol MENU

Halaman HTML yang Anda berikan **tidak memuat API atau `fetch` sama sekali**. Satu-satunya hubungan ke server adalah tombol **MENU**
(`window.location.href = "./menu.html"`), serta berkas pendukung PWA (`sw.js`, `manifest.json`, `display.mp4`).

Karena alamat servernya tidak tertulis di HTML (hanya jalur relatif), aplikasi ini **tidak menebaknya**:
- Pertama kali **MENU** diketuk, aplikasi meminta **alamat halaman TIMER MAXDIS** di server Anda (persis seperti di browser, misalnya
  `https://domain-anda.com/timer/` atau `https://domain-anda.com/timer/index.html`) dan menyimpannya.
- `./menu.html` diselesaikan terhadap alamat itu dengan aturan yang sama seperti browser, lalu dibuka di browser HP.
- **Tekan lama MENU** untuk mengubah alamat. Jika Anda memberi tahu alamatnya, bisa dijadikan nilai bawaan.

## Perbedaan karena ini aplikasi native (jujur)

| Di HTML | Di APK |
|---|---|
| Video `display.mp4` | Animasi bawaan (kotak bergerak di ban berjalan) sebagai pengganti. Video butuh `ffpyplayer` (build berat) dan berkasnya tidak ada pada saya. Jika diperlukan, kirim `display.mp4`. |
| Popup install PWA dan popup update (service worker) | Dihilangkan: tidak relevan untuk APK. Pembaruan dilakukan dengan memasang APK baru. |
| Tekan ENTER di kolom Qty | Tetap bisa. Ditambah tombol **MULAI TIMER (ENTER)** untuk papan ketik yang tidak punya Enter. |
| Emoji peringatan | Diganti tulisan "PERHATIAN:" (font bawaan Kivy tidak punya emoji). Ikon centang digambar langsung. |
| Wake Lock | Layar tetap menyala selama timer berjalan (`FLAG_KEEP_SCREEN_ON`). |
| Bunyi alarm (Web Audio) | Gelombang kotak 900 Hz, 500 ms, tiap detik (dibuat sebagai WAV dengan envelope yang sama). |
| Refresh halaman | Aplikasi ditutup paksa lalu dibuka: bila timer sedang berjalan, hanya lorong yang berjalan yang direset (seperti "reload"); selain itu sesi dikosongkan (seperti membuka halaman baru). |
| Tombol Kembali | Diabaikan saat timer, hasil, atau tutorial tampil agar tidak keluar tidak sengaja. |
| Format tanggal | `dd/MM/yyyy, HH.mm.ss` (id-ID), sama dengan Node.js/Chrome terbaru. Mesin browser lama bisa menulis sedikit berbeda. |

## Pasang di Android lewat GitHub (cara yang sama seperti sebelumnya)

1. Buat repository baru, lalu unggah **semua berkas** dari ZIP: `main.py`, `logic.py`, `test_main.py`, **`golden.json`** (wajib, kunci jawaban uji), `buildozer.spec`,
   `requirements.txt`, `.gitignore`, folder `tools/`, dan folder tersembunyi `.github/workflows/build-apk.yml`.
2. Tab **Actions**: pastikan job **Uji otomatis** hijau.
3. **Actions → Build Android APK → Run workflow → Run workflow** (cabang `main`). Sekitar 30 sampai 45 menit, lalu APK muncul di **Releases** sebagai pre-release `build-N`.
4. Unduh APK di HP, izinkan **Install unknown apps**, lalu pasang. Jika Play Protect memperingatkan, pilih **Install anyway**.

Aplikasi ini tidak meminta izin apa pun dan hanya memakai paket Python murni (`python3`, `kivy`, `pyjnius`, `android`), jadi risiko build paling kecil.
Jika build gagal, buka halaman **Summary** run tersebut (ringkasan error otomatis).

## Pengujian

```
pip install pytest pyyaml
pytest -v test_main.py
```
Membangun ulang kunci jawaban (butuh Node.js): `TZ=Asia/Jakarta node tools/gen_golden.js > golden.json`.
