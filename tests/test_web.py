import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from se02.web.manager import JobManager, ApiError
from se02.web.server import make_server

class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = JobManager(root=self.temp.name)
        self.server = make_server('127.0.0.1', 0, self.manager)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        self.thread.join()
        self.manager.close()
        self.temp.cleanup()
    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port)
        payload = None if body is None else json.dumps(body)
        common = {'Content-Type':'application/json', 'X-SE02-Request':'1', 'Origin':f'http://127.0.0.1:{self.port}'}
        common.update(headers or {})
        connection.request(method, path, payload, common)
        response = connection.getresponse()
        status, data = response.status, response.read()
        connection.close()
        return status, data
    def wait(self, identifier):
        for _ in range(200):
            status, data = self.request('GET', '/api/runs/' + identifier)
            item = json.loads(data)
            if item['status'] not in ('pending','running'):
                return item
            time.sleep(.02)
        self.fail('run did not finish')
    def test_mock_artifacts_history_download(self):
        status, data = self.request('POST','/api/runs', {'mode':'mock','scenario':'repair_pass','max_repairs':2,'task':'ignored custom task'})
        self.assertEqual(status,202,data)
        identifier = json.loads(data)['id']
        item = self.wait(identifier)
        self.assertEqual(item['status'],'succeeded')
        self.assertEqual(len(item['versions']),2)
        self.assertIn('sum(values)',item['versions'][-1]['source'])
        self.assertIn('---',item['diff'])
        self.assertEqual(item['review']['verdict'],'pass')
        self.assertNotEqual(item['task'],'ignored custom task')
        self.assertEqual(self.request('GET',f'/api/runs/{identifier}/download')[0],200)
        recovered = JobManager(root=self.temp.name)
        self.assertEqual(recovered.snapshot(identifier)['status'],'succeeded')
        recovered.close()
    def test_reject_unconfigured_http_unknown_fields_and_bad_origin(self):
        for body in ({'mode':'http','task':'implement'}, {'mode':'mock','api_key':'secret'}, {'mode':'mock','max_repairs':True}):
            self.assertEqual(self.request('POST','/api/runs',body)[0],400)
        self.assertEqual(self.request('POST','/api/runs',{'mode':'mock'}, {'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('GET','/api/config',headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('GET','/api/runs/../../secret')[0],404)
    def test_failure_and_exhaustion_cannot_download(self):
        for scenario, expected in [('call_failure','failed'),('always_reject','needs_attention')]:
            _, data = self.request('POST','/api/runs',{'mode':'mock','scenario':scenario})
            identifier = json.loads(data)['id']
            self.assertEqual(self.wait(identifier)['status'],expected)
            self.assertEqual(self.request('GET',f'/api/runs/{identifier}/download')[0],409)

class WebSecurityTests(WebTests):
    def test_invalid_payload_types_and_secret(self):
        self.manager._secret = 'secret-value'
        bodies = [{'mode':[]},{'scenario':[]},{'mode':'http','task':'secret-value'},{'mode':'mock','task':'x'*10001},{'mode':'mock','max_repairs':3}]
        for body in bodies:
            self.assertEqual(self.request('POST','/api/runs',body)[0],400)
        status,data = self.request('GET','/api/config')
        self.assertEqual(status,200)
        self.assertNotIn(b'secret-value',data)
        self.assertEqual(set(json.loads(data)),{'model','live_available','max_repairs','version'})
    def test_csrf_headers_content_and_limit(self):
        self.assertEqual(self.request('POST','/api/runs',{}, {'X-SE02-Request':'0'})[0],403)
        self.assertEqual(self.request('POST','/api/runs',{}, {'Content-Type':'text/plain'})[0],415)
        self.assertEqual(self.request('POST','/api/runs',{'task':'x'*270000})[0],413)
        self.assertEqual(self.request('GET','/%2e%2e/config.example.toml')[0],404)
        self.assertEqual(self.request('GET','/api/runs/'+'f'*32)[0],404)
    def test_bad_state_does_not_crash_and_download_forbidden(self):
        _,data=self.request('POST','/api/runs',{'mode':'mock'})
        identifier=json.loads(data)['id']
        self.wait(identifier)
        job=self.manager._jobs[identifier]
        self.manager._artifact(job,'state.json').write_text('{broken',encoding='utf-8')
        item=self.manager.snapshot(identifier)
        self.assertEqual(item['status'],'failed')
        self.assertEqual(self.request('GET',f'/api/runs/{identifier}/download')[0],409)
    def test_restart_and_unsafe_metadata(self):
        _,data=self.request('POST','/api/runs',{'mode':'mock'})
        identifier=json.loads(data)['id']
        self.wait(identifier)
        path=Path(self.temp.name)/'ui_metadata'/f'{identifier}.json'
        job=json.loads(path.read_text(encoding='utf-8'))
        job['status']='running'
        path.write_text(json.dumps(job),encoding='utf-8')
        restored=JobManager(root=self.temp.name)
        self.assertEqual(restored.snapshot(identifier)['status'],'failed')
        self.assertIn('resume',restored.snapshot(identifier)['error'])
        restored.close()
        job['core_run_id']='../../private'
        path.write_text(json.dumps(job),encoding='utf-8')
        restored=JobManager(root=self.temp.name)
        self.assertEqual(restored.runs(),{'runs':[]})
        restored.close()
    def test_single_worker_and_injected_provider(self):
        from se02.config import Settings
        from se02.providers import MockProvider
        started,release=threading.Event(),threading.Event()
        class SlowProvider(MockProvider):
            def complete(self,request):
                started.set()
                release.wait(4)
                return super().complete(request)
        with tempfile.TemporaryDirectory() as directory:
            manager=JobManager(root=directory,settings=Settings(api_key='sensitive-value'),provider_factory=SlowProvider)
            try:
                identifier=manager.submit({'mode':'http','task':'implement total'})['id']
                self.assertTrue(started.wait(2))
                with self.assertRaises(ApiError) as caught:
                    manager.submit({'mode':'mock'})
                self.assertEqual(caught.exception.status,409)
                self.assertEqual(manager.snapshot(identifier)['status'],'running')
                with self.assertRaises(ApiError):
                    manager.download(identifier)
            finally:
                release.set()
                manager.close()
            self.assertEqual(manager.snapshot(identifier)['status'],'succeeded')
    def test_crlf_code_is_preserved_and_downloadable(self):
        from se02.providers import MockProvider
        class CrlfProvider(MockProvider):
            def complete(self,request):
                value=json.loads(super().complete(request))
                if request.role=='coder':
                    value['source']=value['source'].replace('\n','\r\n')
                elif request.role=='reviewer':
                    value.update(verdict='pass',issues=[],summary='CRLF accepted')
                return json.dumps(value)
        with tempfile.TemporaryDirectory() as directory:
            manager=JobManager(root=directory,provider_factory=CrlfProvider)
            identifier=manager.submit({'mode':'http','task':'sum'})['id']
            manager.close()
            snapshot=manager.snapshot(identifier)
            self.assertEqual(snapshot['status'],'succeeded')
            self.assertIn('\r\n',snapshot['versions'][0]['source'])
            self.assertIn(b'\r\n',manager.download(identifier))
    def test_missing_final_version_is_failed(self):
        _,data=self.request('POST','/api/runs',{'mode':'mock','scenario':'repair_pass'})
        identifier=json.loads(data)['id']
        self.assertEqual(self.wait(identifier)['status'],'succeeded')
        job=self.manager._jobs[identifier]
        self.manager._artifact(job,'code/v2.json').unlink()
        item=self.manager.snapshot(identifier)
        self.assertEqual(item['status'],'failed')
        self.assertEqual(self.request('GET',f'/api/runs/{identifier}/download')[0],409)
