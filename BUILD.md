# Building YaqeenScan as a single executable

## Requirements

- Windows (admin rights needed at runtime for hotspot/firewall)
- Python 3.10+
- Build dependencies: `pip install -r requirements-build.txt`

## Build

From the project root:

```powershell
.\build.ps1
```

Or manually:

```powershell
pip install -r requirements-build.txt
pyinstaller --noconfirm --clean YaqeenScan.spec
```

## Output

- **Single executable:** `dist\YaqeenScan.exe`
- No console window (windowed app). Data, logs, and exports are created next to the exe when run.

## Running the exe

1. Copy `YaqeenScan.exe` to the folder where you want `data\` and `exports\` to live.
2. Run it; accept UAC elevation when prompted.
3. The app creates `data\yaqeen.db`, `data\yaqeen.log`, `data\qr_cache\`, and `exports\` in the same folder as the exe.
