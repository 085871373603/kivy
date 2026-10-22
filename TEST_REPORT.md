# Test report — Excel Vault

Environment used: Linux x86_64, Python 3.13.5, pytest 9.0.2, pandas 2.2.3, NumPy 2.3.5, openpyxl 3.1.5.

Command executed:

```text
python -m py_compile main.py vault_core.py test_main.py
pytest -v test_main.py
```

Result: **6 passed, 0 failed**.

Test cases passed:

1. CSV delimiter detection and exclusion of header cells from search.
2. Multi-sheet XLSX reading and accurate Excel row/cell output.
3. Counts every match while respecting the display-result limit.
4. Copies an uploaded workbook to local storage and reloads file/index after clearing the in-memory cache.
5. Rejects unsupported file extensions and empty spreadsheets.
6. Migrates an existing storage folder to the new app-local storage path.

Limitations: Kivy is not installed in this test environment, and no Android device/emulator or Android SDK was available. Therefore these results validate the data/storage layer and Python syntax; they do not constitute a successful Android APK build or on-device test of the native document picker. The GitHub Actions workflow is included to build the APK after upload to a repository.
