import tempfile
import unittest
from pathlib import Path
from agent.django_inspection import inspect_django_project
from agent.scanner import scan_repo

def inspect_django_hints(root):
    return inspect_django_project(scan_repo(str(root)))


class DjangoHintTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_literal_evidence_without_execution(self):
        (self.root/'requirements.txt').write_text('Django==4.2.16\n')
        (self.root/'manage.py').write_text("import os\nos.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')\nraise RuntimeError('must never execute')\n")
        report=inspect_django_hints(self.root)
        self.assertEqual(report['eligibility'],'blocked')
        self.assertIn('config.settings',[f['value'] for f in report['findings']])
        self.assertIn('4.2.16',[f['value'] for f in report['findings']])
        self.assertIn('settings_source',[b['code'] for b in report['blockers']])

    def test_comments_and_extension_packages_are_not_django(self):
        (self.root/'requirements.txt').write_text('# Django==5.0\ndjango-extensions==3.2\n-r base.txt\n')
        report=inspect_django_hints(self.root)
        self.assertIsNone(report)

    def test_ambiguous_settings_stay_unresolved(self):
        (self.root/'manage.py').write_text("import os\nos.environ.setdefault('DJANGO_SETTINGS_MODULE','a.settings')\nos.environ.setdefault('DJANGO_SETTINGS_MODULE','b.settings')\n")
        self.assertIn('settings_selection',[b['code'] for b in inspect_django_hints(self.root)['blockers']])

    def test_external_metadata_is_not_read(self):
        (self.root/'requirements.txt').symlink_to('/etc/hosts')
        (self.root/'manage.py').write_text('')
        report=inspect_django_hints(self.root)
        self.assertIn('django_metadata',[b['code'] for b in report['blockers']])


    def settings(self,source):
        (self.root/'manage.py').write_text("import os\nos.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')\n")
        (self.root/'config').mkdir()
        (self.root/'config/settings.py').write_text(source)
        return inspect_django_hints(self.root)

    def test_database_and_environment_names_do_not_expose_values(self):
        report=self.settings("import os\nDATABASES={'default':{'ENGINE':'django.db.backends.postgresql','PASSWORD':'private-password'}}\nSECRET_KEY=os.getenv('DJANGO_SECRET_KEY','private-default')\nraise RuntimeError('never execute')\n")
        self.assertIn('PostgreSQL',[f['value'] for f in report['findings']])
        self.assertIn('DJANGO_SECRET_KEY',[f['value'] for f in report['findings']])
        self.assertNotIn('private-password',str(report))
        self.assertNotIn('private-default',str(report))

    def test_computed_database_is_not_guessed(self):
        report=self.settings('DATABASES=load_database_config()\n')
        self.assertIn('database_dynamic',[b['code'] for b in report['blockers']])
        self.assertFalse(any(f['name']=='database_backend' for f in report['findings']))

    def test_external_settings_source_is_refused(self):
        self.settings('DATABASES={}\n')
        target=self.root/'config/settings.py';target.unlink();target.symlink_to('/etc/hosts')
        report=inspect_django_hints(self.root)
        self.assertIn('django_metadata',[b['code'] for b in report['blockers']])

    def test_multiple_assignments_remain_uncertain(self):
        report=self.settings("DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3'}}\nDATABASES=other_settings()\n")
        self.assertIn('database_dynamic',[b['code'] for b in report['blockers']])
