import tempfile
import time
import unittest
from se02.config import load_config
from se02.domain import CodeArtifact, Task
from se02.providers import MockProvider
from se02.web.manager import JobManager, ApiError
from se02.workflow import Workflow, WorkflowConfig


class UploadTests(unittest.TestCase):
    def test_original_file_is_reviewed_without_coder_call(self):
        provider = MockProvider('repair_pass')
        calls = []
        class Recording:
            def complete(self, request):
                calls.append(request)
                return provider.complete(request)
        source = 'def total(values):\r\n    return sum(values) if values else None\r\n'
        with tempfile.TemporaryDirectory() as root:
            result = Workflow(Recording(), root=root).run(
                Task(task_id='upload', description='Review the uploaded Python code.'),
                WorkflowConfig(max_repairs=2),
                initial_code=CodeArtifact(artifact_id='uploaded',version=1,source=source,explanation='Uploaded file'))
            self.assertEqual(result.state.status, 'succeeded')
            self.assertEqual([r.role for r in calls], ['reviewer','fixer','reviewer'])
            self.assertEqual(calls[0].code.source, source)

    def test_upload_validation_and_history(self):
        with tempfile.TemporaryDirectory() as root:
            manager = JobManager(root=root,provider_factory=lambda:MockProvider('repair_pass'))
            try:
                for filename, source in [('x.exe','abc'),('../x.py','abc'),('x.py',''),('x.py','\x00'),('x.py','x'*32769)]:
                    with self.assertRaises(ApiError):
                        manager.submit({'mode':'http','filename':filename,'source':source})
                source='def total(values):\n    return sum(values) if values else None\n'
                identifier=manager.submit({'mode':'http','filename':'test_total.py','source':source})['id']
                for _ in range(200):
                    item=manager.snapshot(identifier)
                    if item['status'] not in ('running','pending'):break
                    time.sleep(.01)
                self.assertEqual(item['status'],'succeeded')
                self.assertEqual(item['versions'][0]['source'],source)
                self.assertEqual(item['title'],'test_total.py')
                self.assertEqual(item['events'][0]['node'],'upload')
            finally:manager.close()
            restored=JobManager(root=root)
            try:self.assertEqual(restored.snapshot(identifier)['versions'][0]['source'],source)
            finally:restored.close()

    def test_cli_and_web_share_provider_configuration(self):
        config=load_config(environ={'SE02_API_KEY':'test-credential'},config_path='config.example.toml')
        with tempfile.TemporaryDirectory() as root:
            manager=JobManager(root=root,settings=config)
            try:
                self.assertEqual(manager._provider.base_url,config.base_url)
                self.assertEqual(manager._provider.model,config.model)
                self.assertTrue(manager.config()['live_available'])
            finally:manager.close()
