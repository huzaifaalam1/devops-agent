import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typer.testing import CliRunner
from agent.main import app
from agent.scanner import scan_repo
from agent.detector import detect_stack
from agent.docker_generator import propose_docker_files

FIXTURE=Path(__file__).parent/'fixtures/django_inspection/clear'

class DjangoProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'app';shutil.copytree(FIXTURE,self.root)
    def project(self):return detect_stack(scan_repo(str(self.root)))['project']
    def codes(self):return {x['code'] for x in self.project()['blockers']}
    def test_clear_discovery_never_enables_generation(self):
        p=self.project()
        self.assertEqual(p['discovery_status'],'understood');self.assertEqual(p['eligibility'],'blocked')
        self.assertEqual(p['python_version'],'3.12');self.assertEqual(p['services'],['SQLite'])
        self.assertEqual(p['settings_module'],'config.settings')
        self.assertEqual(self.codes(),{'django_execution_not_enabled'})
        self.assertEqual(propose_docker_files(self.root)['status'],'blocked')
        self.assertFalse((self.root/'Dockerfile').exists())
    def test_cli_exposes_django_instead_of_nextjs_error(self):
        result=CliRunner().invoke(app,['analyze',str(self.root),'--json'])
        self.assertNotIn('No declared Next.js',result.output)
        self.assertIn('django_execution_not_enabled',result.output)
    def test_local_requirements_include(self):
        (self.root/'requirements').mkdir();(self.root/'requirements/base.txt').write_text('Django==5.2.8\n')
        (self.root/'requirements.txt').write_text('-r requirements/base.txt\n')
        self.assertEqual(self.project()['discovery_status'],'understood')
    def test_include_cycle_and_escape_refused(self):
        (self.root/'requirements.txt').write_text('-r requirements.txt\n-r ../outside.txt\n')
        self.assertTrue({'requirements_cycle','requirements_include'}<=self.codes())
    def test_conditional_dependency_and_url_are_not_executed(self):
        (self.root/'requirements.txt').write_text('Django==5.2.8; python_version>="3.12"\nthing @ https://private:credential@example.test/x.whl\n')
        p=self.project();self.assertIn('dependency_format',{b['code'] for b in p['blockers']})
        self.assertNotIn('credential',json.dumps(p))
    def test_pin_conflict_and_unpinned_dependency(self):
        (self.root/'requirements.txt').write_text('Django==5.2.8\nDjango==5.2.9\nrequests>=2\n')
        self.assertTrue({'dependency_conflict','dependency_pin'}<=self.codes())
    def test_python_conflict_and_missing(self):
        (self.root/'runtime.txt').write_text('python-3.10\n');self.assertIn('python_conflict',self.codes())
        (self.root/'runtime.txt').unlink();(self.root/'.python-version').unlink()
        self.assertIn('python_selection',self.codes())
    def test_compatibility_patch_threshold(self):
        (self.root/'.python-version').write_text('3.14\n')
        (self.root/'requirements.txt').write_text('Django==5.2.7\n')
        self.assertIn('python_django_compatibility',self.codes())
        (self.root/'requirements.txt').write_text('Django==5.2.8\n')
        self.assertNotIn('python_django_compatibility',self.codes())
    def test_pyproject_constraint_is_checked(self):
        (self.root/'pyproject.toml').write_text('[project]\nrequires-python="<3.12"\n')
        self.assertIn('python_conflict',self.codes())
    def test_dynamic_imported_settings_block(self):
        (self.root/'config/settings.py').write_text('from .base import *\nDATABASES=get_database()\n')
        self.assertTrue({'settings_import','database_dynamic'}<=self.codes())
    def test_environment_names_only_and_postgres_hint(self):
        (self.root/'config/settings.py').write_text("import os\nDATABASES={'default':{'ENGINE':'django.db.backends.postgresql','PASSWORD':os.environ['PG_PASSWORD']}}\nSECRET_KEY=os.getenv('DJANGO_SECRET_KEY','do-not-output')\n")
        p=self.project();self.assertEqual(p['services'],['PostgreSQL'])
        self.assertIn('PG_PASSWORD',json.dumps(p));self.assertNotIn('do-not-output',json.dumps(p))
    def test_conditional_settings_selection(self):
        (self.root/'manage.py').write_text("import os\nif os.getenv('ENV'):\n os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')\n")
        self.assertIn('settings_conditional',self.codes())
    def test_external_settings_symlink_is_not_read(self):
        path=self.root/'config/settings.py';path.unlink();path.symlink_to('/etc/hosts')
        self.assertIn('django_metadata',self.codes())
    def test_mixed_and_multiple_apps_are_not_selected(self):
        (self.root/'package.json').write_text('{"dependencies":{"vue":"3"}}')
        self.assertIn('mixed_stack',self.codes())
        other=self.root/'other';other.mkdir();(other/'manage.py').write_text('')
        self.assertIn('application_selection',self.codes())
    def test_repo_code_is_never_executed(self):
        target=self.root/'executed'
        path=self.root/'manage.py';path.write_text(path.read_text()+f'\nopen({str(target)!r},"w").write("bad")\n')
        self.project();self.assertFalse(target.exists())
    def test_django_extension_is_not_a_django_declaration(self):
        (self.root/'manage.py').unlink();(self.root/'requirements.txt').write_text('django-extensions==3.2.3\n')
        result=detect_stack(scan_repo(str(self.root)))
        self.assertNotIn('Django app',result['detected'])

    def test_unpacked_database_and_other_dependency_manifest_need_review(self):
        (self.root/'config/settings.py').write_text("DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3',**other}}\n")
        (self.root/'pyproject.toml').write_text('[project]\ndependencies=["Django==4.2.16"]\n')
        self.assertTrue({'database_dynamic','dependency_manifests'}<=self.codes())
    def test_unpinned_django_is_recognized_without_manage(self):
        (self.root/'manage.py').unlink();(self.root/'requirements.txt').write_text('Django>=5.2\n')
        self.assertEqual(self.project()['framework'],'Django')
        self.assertIn('dependency_pin',self.codes())
