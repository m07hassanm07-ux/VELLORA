"""Developer-only local extraction of official Windows OCR tools, no installer run.

Not bundled in Waraq releases: install Tesseract separately for deployed OCR.
Requires an existing 7-Zip. Records download hashes for provenance.
"""
from pathlib import Path
import hashlib, json, shutil, subprocess, urllib.request
root = Path(__file__).resolve().parents[1]
folder = root/'.tools'/'tesseract-5.5.3'; folder.mkdir(parents=True, exist_ok=True)
url = 'https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/tesseract-ocr-w64-setup-5.5.3.20260724.exe'
setup = folder/'setup.exe'
if not setup.exists(): urllib.request.urlretrieve(url, setup)
seven = shutil.which('7z') or r'C:\Program Files\7-Zip\7z.exe'
engine = folder/'engine'
if not (engine/'tesseract.exe').exists():
    subprocess.run([seven, 'x', str(setup), '-o'+str(engine), '-y', '-bso0', '-bsp0'], check=True)
records = [{'url': url, 'sha256': hashlib.sha256(setup.read_bytes()).hexdigest()}]
for lang in ('ara', 'eng'):
    source = f'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/{lang}.traineddata'
    target = engine/'tessdata'/(lang+'.traineddata')
    if not target.exists(): urllib.request.urlretrieve(source, target)
    records.append({'url': source, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
(folder/'DOWNLOADS.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
print(engine/'tesseract.exe')
