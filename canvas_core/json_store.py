"""同盘 JSON 持久化：完整写入后替换；错误不伪装为空数据，失败清理临时文件。"""
import copy
import json
import os
from pathlib import Path
import uuid

_MISSING = object()


class DataFileError(OSError):
    """文件不可读、内容损坏或写入失败；调用者不得以空数据覆盖原文件。"""


def read_json(path, default=_MISSING):
    path = Path(path)
    try:
        with path.open('r', encoding='utf-8-sig') as stream:
            return json.load(stream)
    except FileNotFoundError:
        if default is not _MISSING:
            return copy.deepcopy(default)
        raise
    except (OSError, ValueError) as exc:
        raise DataFileError(f'无法读取 {path.name}，原文件已保留，请检查磁盘或从备份恢复。') from exc


def write_json(path, value, *, compact=False):
    path = Path(path)
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open('w', encoding='utf-8', newline='\n') as stream:
            if compact:
                stream.write(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
            else:
                json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise DataFileError(f'无法保存 {path.name}，未完成替换；请检查磁盘空间和文件权限。') from exc
    finally:
        temporary.unlink(missing_ok=True)
