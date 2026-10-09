"""Bounded text configuration edits; repository content is never executed here."""
import difflib
import hashlib
from pathlib import Path
from agent.safety import Redactor

ALLOWED = {'package.json','package-lock.json','Dockerfile','docker-compose.yml','docker-compose.yaml',
           'compose.yml','compose.yaml','.dockerignore','.nvmrc','.node-version','requirements.txt','pyproject.toml'}


def read_config(root, name):
    if name not in ALLOWED:
        raise ValueError('Only supported root configuration files can be read or patched.')
    path=root/name
    if path.is_symlink() or not path.is_file() or path.stat().st_size>256*1024:
        raise ValueError('Select an existing regular configuration file under 256 KiB.')
    text=path.read_text()
    if '\x00' in text or Redactor(root).clean(text)!=text:
        raise ValueError('Configuration contains binary or sensitive content; edit it manually.')
    return text


def preview(root, params):
    before=read_config(root,params['path'])
    old,new=params['old_text'],params['new_text']
    if not old or before.count(old)!=1 or old==new:
        raise ValueError('The old text must match exactly once and the replacement must change it.')
    after=before.replace(old,new,1)
    if len(after.encode())>256*1024 or '\x00' in after or Redactor(root).clean(after)!=after:
        raise ValueError('Replacement is too large or contains sensitive or binary content.')
    if params['path'].endswith('.json'):
        import json
        json.loads(after)
    return {'path':params['path'],'before_sha256':hashlib.sha256(before.encode()).hexdigest(),
            'diff':''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),
                                              fromfile=params['path'],tofile=params['path']))}


def apply(root, params, expected):
    import os
    import tempfile
    from agent.safety import project_lock
    with project_lock(root):
        current=preview(root,params)
        if current!=expected:
            raise ValueError('File changed since review; request a fresh diff.')
        path=root/params['path']
        before=read_config(root,params['path'])
        original=path.stat()
        if original.st_nlink!=1:
            raise ValueError('Hard-linked files cannot be patched.')
        fd,temporary=tempfile.mkstemp(prefix='.devops-edit-',dir=root)
        try:
            with os.fdopen(fd,'w') as stream:
                stream.write(before.replace(params['old_text'],params['new_text'],1))
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary,original.st_mode & 0o777)
            if path.is_symlink() or path.stat()!=original or read_config(root,params['path'])!=before:
                raise ValueError('File changed while applying the patch.')
            os.replace(temporary,path)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)
    return {'success':True,'updated':[params['path']]}
