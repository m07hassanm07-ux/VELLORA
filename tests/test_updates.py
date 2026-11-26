import unittest

from waraq.updates import newer_release


class UpdateTests(unittest.TestCase):
    def test_compares_version_numbers_and_builds_official_link(self):
        release = {
            'tag_name': 'v2.100.0',
            'draft': False,
            'prerelease': False,
            'html_url': 'https://example.invalid/installer',
        }
        self.assertEqual(
            newer_release(release, '2.23.0'),
            ('2.100.0', 'https://github.com/m07hassanm07-ux/VELLORA/releases/tag/v2.100.0'),
        )
        self.assertIsNone(newer_release(release, '2.100.0'))
        self.assertIsNone(newer_release(release, '3.0.0'))

    def test_ignores_drafts_and_prereleases(self):
        release = {'tag_name': 'v3.0.0', 'draft': False, 'prerelease': False}
        for field in ('draft', 'prerelease'):
            with self.subTest(field=field):
                self.assertIsNone(newer_release({**release, field: True}, '2.23.0'))
