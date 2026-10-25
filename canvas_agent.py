"""Agent 命令信箱：接受结构化操作，并可由服务端执行器持久执行。"""
import asyncio
import hashlib
import ipaddress
import inspect
import json
import secrets
import socket
from functools import lru_cache
import time
from pathlib import Path
from threading import RLock
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from canvas_core.json_store import read_json, write_json

ACTIONS = {
    'create_node': '创建素材或当前新版执行节点',
    'duplicate_node': '复制共用节点；原节点抽卡同步副本，副本单独运行后分支',
    'group_nodes': '把指定节点组织为有名称的资产组',
    'update_node': '填写文本、模型、参数、名称和位置',
    'connect': '连接节点，可指定 target_field_key',
    'disconnect': '断开指定节点之间的连接',
    'delete_node': '删除节点（保留素材文件）',
    'run_node': '运行融合节点，返回独立 task_ids，结果进入节点版本',
    'cancel_run': '按 task_id 停止融合节点中的指定任务',
    'arrange': '整理指定节点',
    'snapshot': '读取画布实时状态',
    'production_status': '读取各段的剧本、图片、音频和视频节点实际状态',
    'import_script_segments': '把剧本项目中已保存的分段以来源快照原子导入本画布并登记创作进度；只读写文本，不调用生成模型',
}

class CommandRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=160)
    action: str
    args: Dict[str, Any] = Field(default_factory=dict)

class ClaimRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=160)

class CompleteRequest(ClaimRequest):
    claim_token: str
    status: str
    result: Dict[str, Any] = Field(default_factory=dict)
    error: str = Field(default='', max_length=4000)

class AgentMailbox:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = RLock()
        self.clients = {}

    def path(self, canvas_id):
        if not canvas_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in canvas_id):
            raise HTTPException(400, '无效画布 ID')
        return self.root / f'{canvas_id}.json'

    def read(self, canvas_id):
        path = self.path(canvas_id)
        return read_json(path, default=[])

    def write(self, canvas_id, commands):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path(canvas_id)
        write_json(path, commands)

    @staticmethod
    def public(command):
        return {k: v for k, v in command.items() if k not in {'claim_token', 'fingerprint'}}

    def submit(self, canvas_id, payload):
        if payload.action not in ACTIONS:
            raise HTTPException(400, '不支持的命令；请先读取 /api/agent/capabilities')
        fingerprint = hashlib.sha256(json.dumps([payload.action, payload.args], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            commands = self.read(canvas_id)
            for command in commands:
                if command['request_id'] == payload.request_id:
                    if command['fingerprint'] != fingerprint:
                        raise HTTPException(409, '同一 request_id 不能提交不同操作')
                    return self.public(command)
            if len(commands) >= 10000:
                raise HTTPException(409, '命令记录已达上限，请归档该画布命令记录后继续')
            command = dict(id=secrets.token_hex(16), request_id=payload.request_id, action=payload.action,
                           args=payload.args, fingerprint=fingerprint, status='queued', created_at=time.time())
            commands.append(command)
            self.write(canvas_id, commands)
            return self.public(command)

    def claim(self, canvas_id, client_id):
        with self.lock:
            self.clients[canvas_id] = time.time()
            commands = self.read(canvas_id)
            # 已领取的操作永不自动重投，防止浏览器关闭后重复付费。
            command = next((x for x in commands if x['status'] == 'queued'), None)
            if command:
                command.update(status='running', client_id=client_id, claim_token=secrets.token_hex(24), started_at=time.time())
                self.write(canvas_id, commands)
                return {**self.public(command), 'claim_token': command['claim_token']}
            return None

    def complete(self, canvas_id, command_id, payload):
        if payload.status not in {'succeeded', 'failed'}:
            raise HTTPException(400, '结果状态必须为 succeeded 或 failed')
        with self.lock:
            commands = self.read(canvas_id)
            command = next((x for x in commands if x['id'] == command_id), None)
            if not command:
                raise HTTPException(404, '命令不存在')
            if command.get('client_id') != payload.client_id or not secrets.compare_digest(command.get('claim_token', ''), payload.claim_token):
                raise HTTPException(409, '命令属于其他画布客户端')
            if command['status'] in {'succeeded', 'failed'}:
                return self.public(command)
            command.update(status=payload.status, result=payload.result, error=payload.error, completed_at=time.time())
            self.write(canvas_id, commands)
            return self.public(command)

    def start_backend(self, canvas_id, command_id):
        """仅将排队命令交给服务端；running 命令永不自动重投。"""
        with self.lock:
            commands = self.read(canvas_id)
            command = next((x for x in commands if x['id'] == command_id), None)
            if not command:
                raise HTTPException(404, '命令不存在')
            if command['status'] != 'queued':
                return self.public(command)
            command.update(status='running', executor='server', started_at=time.time())
            self.write(canvas_id, commands)
            return self.public(command)

    def complete_backend(self, canvas_id, command_id, status, result=None, error='', error_status=None):
        if status not in {'succeeded', 'failed'}:
            raise HTTPException(400, '结果状态必须为 succeeded 或 failed')
        with self.lock:
            commands = self.read(canvas_id)
            command = next((x for x in commands if x['id'] == command_id), None)
            if not command:
                raise HTTPException(404, '命令不存在')
            if command['status'] in {'succeeded', 'failed'}:
                return self.public(command)
            command.update(status=status, result=result or {}, error=error or '', completed_at=time.time())
            if error_status is not None:
                command['error_status'] = int(error_status)
            self.write(canvas_id, commands)
            return self.public(command)


@lru_cache(maxsize=2)
def local_addresses(time_bucket):
    """识别服务器自身地址；UDP connect 只查询路由，不发送数据。"""
    addresses = {'127.0.0.1', '::1'}
    try:
        addresses.update(item[4][0].split('%')[0] for item in socket.getaddrinfo(socket.gethostname(), None))
    except OSError:
        pass
    for family, target in [(socket.AF_INET, ('192.0.2.1', 9)), (socket.AF_INET6, ('2001:db8::1', 9))]:
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as sock:
                sock.connect(target)
                addresses.add(sock.getsockname()[0].split('%')[0])
        except OSError:
            pass
    return addresses


def is_local_client(host):
    if host == 'testclient':
        return True
    try:
        address = ipaddress.ip_address(host.split('%')[0])
        address = getattr(address, 'ipv4_mapped', None) or address
        return address.is_loopback or str(address) in local_addresses(int(time.time() // 30))
    except ValueError:
        return False


def create_agent_router(root, load_canvas, executor=None):
    mailbox = AgentMailbox(Path(root) / 'data' / 'agent_commands')
    router = APIRouter(prefix='/api/agent', tags=['Canvas Agent'])
    backend_executor = getattr(executor, 'execute', executor) if executor is not None else None
    backend_tasks = {}

    def schedule_backend(canvas_id, command):
        if backend_executor is None or command.get('status') != 'queued':
            return command
        started = mailbox.start_backend(canvas_id, command['id'])
        if started.get('status') != 'running':
            return started

        async def run_backend():
            try:
                result = backend_executor(canvas_id, command['action'], command.get('args') or {}, command['request_id'])
                if inspect.isawaitable(result):
                    result = await result
                mailbox.complete_backend(canvas_id, command['id'], 'succeeded', result=result if isinstance(result, dict) else {'value': result})
            except BaseException as exc:
                detail = getattr(exc, 'detail', None) or str(exc) or exc.__class__.__name__
                error = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False, sort_keys=True)
                try:
                    mailbox.complete_backend(canvas_id, command['id'], 'failed', error=error,
                                             error_status=getattr(exc, 'status_code', None))
                except Exception:
                    # 原命令已进入 running；不能因为写回异常而创建第二次执行。
                    pass

        task = asyncio.create_task(run_backend())
        backend_tasks[command['id']] = task

        def forget(done):
            backend_tasks.pop(command['id'], None)
            try:
                done.exception()
            except (asyncio.CancelledError, Exception):
                pass

        task.add_done_callback(forget)
        return started

    async def local_request(request: Request):
        host = request.client.host if request.client else ''
        # 允许启动器打开的本机局域网地址，但不把其他电脑等同于本机。
        if not await run_in_threadpool(is_local_client, host):
            raise HTTPException(403, '请在运行画布服务的电脑上连接 Agent；可使用当前本机地址或 127.0.0.1')
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, '不允许跨站操作画布')

    from fastapi import Depends
    router.dependencies.append(Depends(local_request))

    @router.get('/capabilities')
    async def capabilities():
        return {'protocol_version': 1, 'name': '老胡创意工作台', 'transport': 'http-json',
                'requires_open_canvas': backend_executor is None, 'defaults': '/api/agent/canvases/{canvas_id}/defaults', 'guide': '/api/agent/guide', 'openapi': '/openapi.json',
                'node_index': '/api/agent/canvases/{canvas_id}/nodes',
                'node_context': '/api/agent/canvases/{canvas_id}/nodes/{node_id}',
                'actions': ACTIONS, 'models': '/api/model-capabilities', 'canvases': '/api/canvases',
                'submit': '/api/agent/canvases/{canvas_id}/commands',
                'asset_library': '/api/asset-library', 'asset_group_create': '/api/asset-library/categories',
                'asset_move': '/api/asset-library/items/move',
                'idempotency': '同一画布中 request_id 永久去重；超时查询原命令，不能重新提交付费运行。'}

    @router.get('/guide', response_class=PlainTextResponse)
    async def guide():
        return (Path(root) / 'static' / 'agent-guide.md').read_text(encoding='utf-8')

    @router.get('/canvases/{canvas_id}/defaults')
    async def defaults(canvas_id: str):
        canvas = load_canvas(canvas_id)
        return {'canvas_id': canvas_id, 'defaults': canvas.get('settings', {}).get('agentDefaults', {}),
                'precedence': '用户明确指定的字段 > 当前画布 Agent 默认值；换模型不继承旧模型参数。未设置默认时请先配置。'}

    @router.get('/canvases/{canvas_id}/nodes')
    async def node_index(canvas_id: str):
        canvas = await run_in_threadpool(load_canvas, canvas_id)
        return {'canvas_id': canvas_id, 'nodes': [
            {key: node[key] for key in ('id', 'displayNumber', 'title', 'type', 'creationRevision') if key in node}
            for node in canvas.get('nodes') or []]}

    @router.get('/canvases/{canvas_id}/nodes/{node_id}')
    async def node_context(canvas_id: str, node_id: str):
        canvas = await run_in_threadpool(load_canvas, canvas_id)
        node = next((n for n in canvas.get('nodes') or [] if n.get('id') == node_id), None)
        if node is None:
            raise HTTPException(404, '节点不存在')
        # 完整返回当前内容；历史任务和其他段正文不会挤占 Agent 上下文。
        from canvas_core.creation_records import creation_record
        context = creation_record(node)
        context.update({key: node[key] for key in ('id', 'displayNumber', 'creationRevision', 'images', 'items', 'activeResultVersion', 'production') if key in node})
        return {'canvas_id': canvas_id, 'node': context,
                'connections': [c for c in canvas.get('connections') or [] if node_id in (c.get('from'), c.get('to'))],
                'source': 'saved_canvas'}

    @router.get('/canvases/{canvas_id}/commands')
    async def commands(canvas_id: str):
        load_canvas(canvas_id)
        with mailbox.lock:
            items = [mailbox.public(x) for x in mailbox.read(canvas_id)]
        return {'commands': items, 'connected': time.time() - mailbox.clients.get(canvas_id, 0) < 15}

    @router.post('/canvases/{canvas_id}/commands')
    async def submit(canvas_id: str, payload: CommandRequest):
        load_canvas(canvas_id)
        command = mailbox.submit(canvas_id, payload)
        if (backend_executor is not None and command.get('status') == 'running'
            and command.get('action') == 'import_script_segments'):
            active = backend_tasks.get(command['id'])
            if active is not None and not active.done():
                return command
            # Import is a pure, durable graph transaction. Re-running the same
            # request after a lost mailbox response is safe: scriptImports
            # returns the committed receipt or the canvas lock performs it once.
            try:
                result = backend_executor(canvas_id, command.get('action'), command.get('args') or {}, command['request_id'])
                if inspect.isawaitable(result):
                    result = await result
                return mailbox.complete_backend(canvas_id, command['id'], 'succeeded',
                    result=result if isinstance(result, dict) else {'value': result})
            except BaseException as exc:
                detail = getattr(exc, 'detail', None) or str(exc) or exc.__class__.__name__
                error = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False, sort_keys=True)
                return mailbox.complete_backend(canvas_id, command['id'], 'failed', error=error,
                    error_status=getattr(exc, 'status_code', None))
        return schedule_backend(canvas_id, command)

    @router.get('/canvases/{canvas_id}/commands/{command_id}')
    async def command(canvas_id: str, command_id: str):
        with mailbox.lock:
            item = next((x for x in mailbox.read(canvas_id) if x['id'] == command_id), None)
        if not item:
            raise HTTPException(404, '命令不存在')
        return mailbox.public(item)

    @router.post('/canvases/{canvas_id}/claim')
    async def claim(canvas_id: str, payload: ClaimRequest):
        if backend_executor is not None:
            raise HTTPException(410, '服务端已执行 Agent 命令，浏览器不得 claim')
        load_canvas(canvas_id)
        return {'command': mailbox.claim(canvas_id, payload.client_id)}

    @router.post('/canvases/{canvas_id}/commands/{command_id}/complete')
    async def complete(canvas_id: str, command_id: str, payload: CompleteRequest):
        if backend_executor is not None:
            raise HTTPException(410, '服务端已执行 Agent 命令，浏览器不得 complete')
        return mailbox.complete(canvas_id, command_id, payload)

    return router
