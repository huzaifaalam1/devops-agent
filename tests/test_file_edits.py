import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent.tools import ToolRegistry


class FileEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'app';self.root.mkdir()
        self.file=self.root/'package.json';self.file.write_text('{"name":"demo"}\n')
        self.registry=ToolRegistry(self.root)
        self.params={'path':'package.json','old_text':'"demo"','new_text':'"updated"'}
        env=patch.dict(os.environ,{'DEVOPS_AGENT_STATE_DIR':str(Path(self.tmp.name)/'state')})
        env.start();self.addCleanup(env.stop)

    def review(self):return self.registry.review('patch_file',self.params)

    def test_review_apply_and_no_replay(self):
        review=self.review()
        self.assertIn('-{"name":"demo"}',review['preview']['diff'])
        self.assertIn('demo',self.file.read_text())
        token=self.registry.approve(review['review_id'])
        self.registry.execute('patch_file',self.params,approval=token)
        self.assertIn('updated',self.file.read_text())
        with self.assertRaises(ValueError):self.registry.execute('patch_file',self.params,approval=token)

    def test_stale_file_at_approval_and_execution(self):
        review=self.review();self.file.write_text('{"name":"changed"}')
        with self.assertRaises(ValueError):self.registry.approve(review['review_id'])
        self.file.write_text('{"name":"demo"}\n');review=self.review()
        token=self.registry.approve(review['review_id']);self.file.write_text('{"name":"changed"}')
        with self.assertRaises(ValueError):self.registry.execute('patch_file',self.params,approval=token)
        self.assertIn('changed',self.file.read_text())

    def test_no_approval_or_unsafe_paths(self):
        with self.assertRaises(ValueError):self.registry.execute('patch_file',self.params)
        for name in ['../package.json','.env','.git/config','node_modules/package.json','/tmp/package.json']:
            with self.assertRaises(ValueError):self.registry.execute('read_file',{'path':name})
        self.file.unlink();self.file.symlink_to('/tmp/outside')
        with self.assertRaises(ValueError):self.review()

    def test_large_dependencies_do_not_affect_file_review(self):
        deps=self.root/'node_modules';deps.mkdir()
        with (deps/'large').open('wb') as stream:stream.truncate(3*1024**3)
        review=self.review()
        token=self.registry.approve(review['review_id'])
        self.registry.execute('patch_file',self.params,approval=token)
        self.assertIn('updated',self.file.read_text())

    def test_invalid_or_ambiguous_patch(self):
        for old,new in [('missing','x'),('','x'),('"demo"','invalid-json')]:
            with self.assertRaises(ValueError):self.registry.review('patch_file',{**self.params,'old_text':old,'new_text':new})
