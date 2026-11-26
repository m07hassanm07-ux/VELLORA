"""Read release metadata without downloading or launching installers."""

import json
import re
from urllib.request import Request, urlopen

REPOSITORY = 'm07hassanm07-ux/VELLORA'
RELEASES = f'https://github.com/{REPOSITORY}/releases'


def _version(value):
    match = re.fullmatch(r'v?([0-9]{1,6})\.([0-9]{1,6})\.([0-9]{1,6})', value)
    if not match:
        raise ValueError('رقم الإصدار غير صالح.')
    return tuple(map(int, match.groups()))


def newer_release(payload, current):
    if payload.get('draft') is not False or payload.get('prerelease') is not False:
        return None
    tag = payload['tag_name']
    version = _version(tag)
    if version <= _version(current):
        return None
    label = '.'.join(map(str, version))
    return label, f'{RELEASES}/tag/{tag}'


def check_for_update(current):
    request = Request(
        f'https://api.github.com/repos/{REPOSITORY}/releases/latest',
        headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'VELLORA'},
    )
    with urlopen(request, timeout=8) as response:
        body = response.read(1024 * 1024 + 1)
    if len(body) > 1024 * 1024:
        raise ValueError('بيانات الإصدار أكبر من الحد المتوقع.')
    return newer_release(json.loads(body), current)
