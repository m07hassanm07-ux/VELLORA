"""Run an explicitly selected local veraPDF CLI and read its XML report."""
from pathlib import Path
import os
import subprocess
from tempfile import TemporaryDirectory
from xml.etree import ElementTree


def parse_report(xml):
    root = ElementTree.fromstring(xml)
    reports = root.findall('./jobs/job/validationReport')
    if len(reports) != 1 or reports[0].get('isCompliant') not in ('true', 'false'):
        raise ValueError('لم يُرجع veraPDF نتيجة تحقق صالحة لملف واحد.')
    report = reports[0]
    failures = []
    for rule in report.findall('./details/rule'):
        if rule.get('status') == 'failed':
            clause = rule.get('clause', '')
            description = rule.findtext('description') or rule.findtext('test') or ''
            failures.append(f'{clause} — {description.strip()}')
    return report.get('isCompliant') == 'true', failures


def validate_pdfua(program, data, profile):
    launcher = Path(program).resolve(strict=True)
    if profile not in ('ua1', 'ua2'):
        raise ValueError('اختر معيار PDF/UA-1 أو PDF/UA-2.')
    args = ['--format', 'xml', '--flavour', profile, 'document.pdf']
    command = [str(launcher), *args]
    if launcher.suffix.lower() in ('.bat', '.cmd'):
        if os.name != 'nt' or any(char in str(launcher) for char in '%!&|<>^"\r\n'):
            raise ValueError('اختر مسارًا محليًا بسيطًا لملف تشغيل veraPDF.')
        shell = Path(os.environ['SystemRoot']) / 'System32' / 'cmd.exe'
        command = f'"{shell}" /d /s /v:off /c ""{launcher}" {" ".join(args)}"'
    with TemporaryDirectory(prefix='vellora-pdfua-') as folder:
        (Path(folder) / 'document.pdf').write_bytes(data)
        try:
            result = subprocess.run(command, cwd=folder, stdin=subprocess.DEVNULL,
                                    capture_output=True, timeout=90,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as exc:
            raise ValueError('تجاوز فحص veraPDF المهلة المحددة.') from exc
        try:
            return parse_report(result.stdout)
        except (ValueError, ElementTree.ParseError) as exc:
            detail = result.stderr.decode('utf-8', errors='replace').strip()[-800:]
            raise ValueError(f'تعذر قراءة تقرير veraPDF. تحقق من تثبيت الإصدار الداعم لـ PDF/UA.\n{detail}') from exc
