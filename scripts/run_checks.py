from pathlib import Path
import json,os,site,sys,unittest
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/'.deps')]
if (root/'.deps').exists():site.addsitedir(str(root/'.deps'))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
suite=unittest.defaultTestLoader.discover(str(root/'tests'))
result=unittest.TextTestRunner(verbosity=2).run(suite)
report={'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'passed':result.wasSuccessful()}
(root/'docs'/'test-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
raise SystemExit(0 if result.wasSuccessful() else 1)
