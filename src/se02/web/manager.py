"""Isolated UI job history and one background workflow worker."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import difflib
import json
import os
from pathlib import Path
import re
from threading import RLock
from uuid import uuid4

from se02.cli import DEMO_TASK
from se02.config import Settings
from se02.domain import CodeArtifact, ExecutionEvent, ReviewReport, RunState, Task, ValidationError
from se02.providers import HttpProvider, MockProvider
from se02.workflow import Workflow, WorkflowConfig

ID = re.compile(r'[a-f0-9]{32}\Z')
SCENARIOS = {'direct_pass','repair_pass','always_reject','call_failure'}
TERMINAL = {'succeeded','failed','needs_attention'}


def _shared_bytes(path):
    """Allow core atomic replacement while UI reads snapshots on Windows."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        import msvcrt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        handle = create(str(path), 0x80000000, 7, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        with os.fdopen(descriptor, 'rb') as stream:
            value = stream.read(2 * 1024 * 1024 + 1)
    else:
        with path.open('rb') as stream:
            value = stream.read(2 * 1024 * 1024 + 1)
    if len(value)>2*1024*1024:
        raise ValueError('artifact too large')
    return value

class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status

class JobManager:
    def __init__(self, *, root='runs/web', settings=None, provider_factory=None):
        self.root = Path(root).resolve()
        self.settings = settings or Settings()
        self._secret = self.settings.api_key
        self._factory = provider_factory
        self._provider = None
        if provider_factory is None and self.settings.base_url and self.settings.model and self.settings.api_key:
            self._provider = HttpProvider(base_url=self.settings.base_url, model=self.settings.model,
                api_key=self.settings.api_key, timeout=self.settings.timeout,
                max_retries=self.settings.max_retries, retry_delay=self.settings.retry_delay)
        self._lock = RLock()
        self._jobs = {}
        self._active = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='se02-web')
        self._directory('ui_metadata').mkdir(parents=True, exist_ok=True)
        self._directory('artifacts').mkdir(parents=True, exist_ok=True)
        self._restore()

    def _directory(self, *parts):
        candidate = self.root
        for part in parts:
            if not isinstance(part, str) or part in ('', '.', '..') or '/' in part or '\\' in part:
                raise ApiError(400, 'Unsafe artifact reference')
            candidate = candidate / part
            # Avoid resolving a live file: Windows realpath briefly opens it without
            # delete sharing and can block the core atomic state replacement.
            if candidate.is_symlink() or (hasattr(candidate, 'is_junction') and candidate.is_junction()):
                raise ApiError(400, 'Unsafe artifact reference')
        return candidate

    def safe(self, value):
        if isinstance(value, str):
            return value.replace(self._secret, '[REDACTED]') if self._secret else value
        if isinstance(value, list):
            return [self.safe(v) for v in value]
        if isinstance(value, dict):
            return {k:self.safe(v) for k,v in value.items()}
        return value

    def config(self):
        return self.safe({'model':self.settings.model, 'live_available': self._provider is not None or self._factory is not None,
            'max_repairs': self.settings.max_repairs, 'version':'0.3.1'})

    def _save(self, job):
        target = self._directory('ui_metadata', job['id'] + '.json')
        temporary = self._directory('ui_metadata', job['id'] + '.tmp')
        temporary.write_text(json.dumps(self.safe(job), ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, target)

    def _read_json(self, path):
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('artifact too large')
        return json.loads(_shared_bytes(path).decode('utf-8'))

    def _restore(self):
        for path in self._directory('ui_metadata').glob('*.json'):
            if not ID.fullmatch(path.stem):
                continue
            try:
                job = self._read_json(self._directory('ui_metadata', path.name))
                required = {'id','title','task','mode','scenario','status','created_at','repair_count','current_node','core_run_id','error','result','max_repairs'}
                if not isinstance(job,dict) or set(job) not in (required, required | {'filename','uploaded_source'}) or job['id'] != path.stem:
                    continue
                if job['mode'] not in ('http','mock') or job['scenario'] not in SCENARIOS or job['status'] not in TERMINAL | {'pending','running'}:
                    continue
                if job['core_run_id'] is not None and not ID.fullmatch(job['core_run_id']):
                    continue
                Task(task_id=job['id'], description=job['task'])
                if type(job['repair_count']) is not int or not 0 <= job['repair_count'] <= 2 or type(job['max_repairs']) is not int or not 0 <= job['max_repairs'] <= 2:
                    continue
                if not isinstance(job['title'],str) or not isinstance(job['created_at'],str):
                    continue
                if 'uploaded_source' in job and (not isinstance(job['uploaded_source'],str)
                        or not isinstance(job['filename'],str) or len(job['uploaded_source'].encode('utf-8'))>32768):
                    continue
                # Stored references are never accepted as paths; derived artifacts use fixed names.
                job['result'] = None
                if job['status'] in ('running','pending'):
                    job.update(status='failed', error='Server restarted before completion; resume is not supported.')
                self._jobs[job['id']] = self.safe(job)
                self._save(job)
            except (OSError, ValueError, TypeError, ValidationError, ApiError):
                continue

    def runs(self):
        with self._lock:
            return {'runs':[self.safe({**{k:j[k] for k in ('id','title','status','mode','created_at','repair_count')},'filename':j.get('filename')})
                for j in sorted(self._jobs.values(), key=lambda j:j['created_at'], reverse=True)]}

    def submit(self, body):
        if not isinstance(body,dict) or set(body) - {'task','mode','scenario','max_repairs','filename','source'}:
            raise ApiError(400,'Unknown request fields or invalid JSON object')
        uploaded = 'filename' in body or 'source' in body
        if uploaded:
            filename, source = body.get('filename'), body.get('source')
            if (not isinstance(filename,str) or not re.fullmatch(r'[^/\\\x00-\x1f:]{1,120}\.py',filename,re.I)
                    or filename in ('.py','..py') or not isinstance(source,str) or not source.strip()
                    or '\x00' in source or any(0xD800 <= ord(c) <= 0xDFFF for c in source)
                    or len(source.encode('utf-8',errors='replace')) > 32768):
                raise ApiError(400,'Upload a nonempty UTF-8 .py file of at most 32 KiB')
            if body.get('mode','http') != 'http' or 'scenario' in body or 'task' in body:
                raise ApiError(400,'Uploaded files use the CLI HTTP model configuration only')
            if self._secret and self._secret in source:
                raise ApiError(400,'File must not contain the configured credential')
            body = dict(body, mode='http', task='审查上传的 Python 文件 '+filename+'，重点检查核心逻辑与关键边界缺陷（如除零异常 ZeroDivisionError、空输入等），每次审查完后用中文给出本次审查结论；修复时遵循最小改动原则，保持代码简洁直观，保留原有功能和公开接口。')
        mode, scenario = body.get('mode','mock'), body.get('scenario','direct_pass')
        repairs = body.get('max_repairs', self.settings.max_repairs)
        if not isinstance(mode,str) or not isinstance(scenario,str) or mode not in ('mock','http') or scenario not in SCENARIOS or type(repairs) is not int or not 0 <= repairs <= 2:
            raise ApiError(400,'Invalid mode, scenario or repair budget')
        supplied = body.get('task','')
        if not isinstance(supplied,str) or len(supplied)>10000:
            raise ApiError(400,'Task must be text of at most 10000 characters')
        if self._secret and self._secret in supplied:
            raise ApiError(400,'Task must not contain the configured credential')
        description = DEMO_TASK if mode == 'mock' else supplied
        try:
            Task(task_id='validation', description=description)
        except ValidationError:
            raise ApiError(400,'Task must be nonempty text of at most 10000 characters') from None
        if mode == 'http' and not self.config()['live_available']:
            raise ApiError(400,'Real model is not configured; set server configuration and SE02_API_KEY')
        with self._lock:
            if self._active is not None:
                raise ApiError(409,'A workflow is already running')
            identifier = uuid4().hex
            job = {'id':identifier,'title':description.strip().splitlines()[0][:80],'task':description,'mode':mode,
                'scenario':scenario,'status':'pending','created_at':datetime.now(timezone.utc).isoformat(),
                'repair_count':0,'current_node':None,'core_run_id':None,'error':None,'result':None,'max_repairs':repairs}
            if uploaded:
                job.update(title=filename, filename=filename, uploaded_source=source)
            try:
                self._save(job)
            except OSError:
                raise ApiError(500,'Cannot persist UI job') from None
            self._jobs[identifier] = job
            self._active = identifier
            self._executor.submit(self._execute, identifier)
            return {'id':identifier}

    def _execute(self, identifier):
        try:
            with self._lock:
                job = self._jobs[identifier]
                job['status'] = 'running'
                self._save(job)
            provider = MockProvider(job['scenario']) if job['mode']=='mock' else self._factory() if self._factory else self._provider
            def event_callback(event):
                with self._lock:
                    job.update(core_run_id=event.run_id,current_node=event.node)
                    if event.node.startswith('repair_') and event.status != 'skipped':
                        job['repair_count'] = max(job['repair_count'],int(event.node.split('_')[1]))
                    self._save(job)
            result = Workflow(provider, root=self._directory('artifacts',identifier), on_event=event_callback).run(
                Task(task_id=identifier, description=job['task']), WorkflowConfig(max_repairs=job['max_repairs']),
                initial_code=CodeArtifact(artifact_id='upload-'+identifier,version=1,source=job['uploaded_source'],
                    explanation='Original uploaded Python source') if 'uploaded_source' in job else None)
            with self._lock:
                job.update(core_run_id=result.state.run_id, status=result.state.status,repair_count=result.state.repair_count,
                    current_node=result.state.current_node,error='Workflow failed; inspect the timeline.' if result.state.error else None,
                    result={'status':result.state.status,'final_code_ref':result.final_code_ref,
                        'final_review_ref':result.final_review_ref,
                        'persistence_errors':['Artifact persistence failed.'] if result.persistence_errors else []})
                self._save(job)
        except Exception:
            with self._lock:
                self._jobs[identifier].update(status='failed',error='The workflow could not complete. Check server configuration and artifact storage.')
                try:
                    self._save(self._jobs[identifier])
                except (OSError, ApiError):
                    pass
        finally:
            with self._lock:
                self._active = None

    def _artifact(self, job, ref):
        core = job['core_run_id']
        if not core or not ID.fullmatch(core):
            raise ValueError('no core run')
        # refs only originate from fixed names below, never API parameters/metadata.
        return self._directory('artifacts',job['id'],core,*Path(ref).parts)

    def snapshot(self, identifier):
        if not ID.fullmatch(identifier):
            raise ApiError(404,'Run not found')
        with self._lock:
            if identifier not in self._jobs:
                raise ApiError(404,'Run not found')
            job = deepcopy(self._jobs[identifier])
        snapshot = {k:job[k] for k in ('id','title','task','mode','scenario','status','created_at','repair_count','current_node','error','result')}
        snapshot.update(events=[],versions=[],reviews=[],review=None,diff='')
        corrupt = False
        if job['core_run_id']:
            try:
                for version in (1,2,3):
                    artifact_path = self._artifact(job,f'code/v{version}.json')
                    if not artifact_path.exists():
                        continue
                    artifact = CodeArtifact.from_dict(self._read_json(artifact_path))
                    source_path = self._artifact(job,f'code/v{version}.py')
                    if source_path.stat().st_size>2*1024*1024 or _shared_bytes(source_path) != artifact.source.encode('utf-8') or artifact.version!=version:
                        raise ValueError('mismatched code')
                    snapshot['versions'].append({'version':version,'source':artifact.source})
                for index in (0,1,2):
                    path = self._artifact(job,f'reviews/review_{index}.json')
                    if path.exists():
                        snapshot['reviews'].append(ReviewReport.from_dict(self._read_json(path)).to_dict())
                events_path = self._artifact(job,'events.jsonl')
                if events_path.exists():
                    if events_path.stat().st_size>2*1024*1024:
                        raise ValueError('event log too large')
                    event_text = _shared_bytes(events_path).decode('utf-8')
                    lines = event_text.splitlines()
                    if job['status'] in ('pending','running') and event_text and not event_text.endswith('\n'):
                        lines = lines[:-1]  # A concurrent append has not published its whole line yet.
                    for line in lines:
                        try:
                            event = ExecutionEvent.from_dict(json.loads(line))
                            if event.run_id != job['core_run_id']:
                                raise ValueError('event from wrong run')
                            value = event.to_dict()
                            # Adapter errors can include machine paths; keep API diagnostics fixed.
                            if value['status']=='failed':
                                value['detail']='Request or workflow step failed.'
                            snapshot['events'].append(value)
                        except (ValueError, ValidationError):
                            corrupt = True
                if job['status'] in TERMINAL:
                    state_path = self._artifact(job,'state.json')
                    if state_path.exists():
                        state = RunState.from_dict(self._read_json(state_path))
                        if state.run_id != job['core_run_id'] or (job['status']=='succeeded' and state.status!='succeeded'):
                            raise ValueError('state from wrong run')
                        # Validate refs without ever opening caller-controlled paths.
                        allowed = re.compile(r'(task\.json|code/v[1-3]\.(py|json)|reviews/review_[0-2]\.json|fixes/fix_v[23]\.json|messages/[a-f0-9]{32}\.json)\Z')
                        if any(not allowed.fullmatch(ref) for ref in state.artifact_refs+state.message_refs):
                            raise ValueError('invalid state refs')
                        if any(not self._artifact(job,ref).is_file() for ref in state.artifact_refs+state.message_refs):
                            raise ValueError('missing referenced artifact')
                    elif job['status']=='succeeded':
                        raise ValueError('missing success state')
            except (OSError, ValueError, ValidationError, ApiError, TypeError):
                corrupt = True
        if snapshot['versions']:
            latest = snapshot['versions'][-1]
            snapshot['review'] = next((r for r in reversed(snapshot['reviews']) if r['artifact_version']==latest['version']),None)
            if len(snapshot['versions'])>1:
                first = snapshot['versions'][0]
                snapshot['diff'] = ''.join(difflib.unified_diff(first['source'].splitlines(keepends=True),latest['source'].splitlines(keepends=True),fromfile=f"v{first['version']}.py",tofile=f"v{latest['version']}.py"))
        if job['status']=='succeeded' and (not snapshot['versions'] or not snapshot['review'] or snapshot['review']['verdict']!='pass'):
            corrupt = True
        if corrupt and job['status'] not in ('pending','running'):
            snapshot.update(status='failed',error='Stored artifacts are incomplete or invalid; download is unavailable.',result=None)
        return self.safe(snapshot)

    def download(self, identifier):
        snapshot = self.snapshot(identifier)
        if snapshot['status'] != 'succeeded' or not snapshot['versions'] or not snapshot['review'] or snapshot['review']['verdict']!='pass':
            raise ApiError(409,'Only a successfully completed run can be downloaded')
        return snapshot['versions'][-1]['source'].encode('utf-8')

    def close(self):
        self._executor.shutdown(wait=True, cancel_futures=False)
