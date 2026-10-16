"""Static Node startup adapters; never evaluate JavaScript or run package scripts."""
import re
import shlex
from agent.understanding import read_text


def framework(deps):
    if 'next' in deps: return 'Next.js'
    if 'vite' in deps: return 'Vue/Vite' if 'vue' in deps else 'Vite'
    if '@vue/cli-service' in deps: return 'Vue CLI'
    return 'Node.js'


def startup(root, package, kind):
    scripts = package.get('scripts', {})
    if not isinstance(scripts, dict): raise ValueError('Declare package scripts for local startup.')
    name = 'dev' if scripts.get('dev') else 'serve' if kind == 'Vue CLI' and scripts.get('serve') else 'start'
    value = scripts.get(name)
    tokens = shlex.split(value) if isinstance(value, str) else []
    if scripts.get('pre'+name) or scripts.get('post'+name):
        raise ValueError('Review startup lifecycle hooks before generating a container.')
    if kind in {'Vue/Vite','Vite','Vue CLI'}:
        if tokens[:3] == ['node','--no-warnings','./node_modules/.bin/vite']:
            tokens = ['vite', *tokens[3:]]
        if tokens[:2] in (['vite','dev'],['vite','serve']): tokens = ['vite',*tokens[2:]]
        base = ['vue-cli-service','serve'] if kind == 'Vue CLI' else ['vite']
        if tokens[:len(base)] != base: raise ValueError('Cannot establish a direct Vite or Vue CLI development command.')
        port = 8080 if kind == 'Vue CLI' else 5173
        config_names = ('vue.config.js','vue.config.cjs') if kind == 'Vue CLI' else ('vite.config.js','vite.config.ts','vite.config.mjs','vite.config.mts')
        configs = [name for name in config_names if (root/name).exists()]
        if len(configs)>1: raise ValueError('Multiple development-server config files require selection.')
        for filename in configs:
            text=read_text(root,filename)
            # Only a literal port is inferred. Dynamic configuration is not executed.
            bodies=re.findall(r'(?:server|devServer)\s*:\s*\{([^}]+)',text)
            values=[v.strip() for body in bodies for v in re.findall(r'\bport\s*:\s*([^,}\n]+)',body)]
            if values:
                if len(set(values))!=1 or not values[0].isdigit() or not 1<=int(values[0])<=65535:
                    raise ValueError('Development-server port is dynamic or ambiguous; clarify it before generation.')
                port=int(values[0])
        rest = tokens[len(base):]
        while rest:
            token = rest.pop(0)
            if token == '--strictPort': continue
            flag, sep, arg = token.partition('=')
            if not sep:
                arg = rest.pop(0) if rest and not rest[0].startswith('-') else ''
            if flag == '--host' and arg in ('','0.0.0.0','::','localhost','127.0.0.1'): continue
            if flag in ('--port','-p') and arg.isdigit() and 1 <= int(arg) <= 65535: port=int(arg);continue
            raise ValueError('Review custom development-server flags or shell commands before generation.')
        # Explicit arguments override Vite config/default localhost binding and disable port fallback.
        command = ['npm','run',name,'--','--host','0.0.0.0','--port',str(port)]
        if kind != 'Vue CLI': command.append('--strictPort')
        return command, port, name
    if len(tokens) != 2 or tokens[0] != 'node' or not re.fullmatch(r'[\w./-]+\.(?:js|mjs|cjs)',tokens[1]):
        raise ValueError('Generic Node generation requires a direct node entrypoint and statically evidenced listening port; existing Compose can be reviewed separately.')
    source=read_text(root,tokens[1])
    ports=set(re.findall(r'\.listen\(\s*(\d{1,5})\s*[,)]',source))
    if len(ports)!=1 or not 1<=int(next(iter(ports)))<=65535:
        raise ValueError('Cannot establish one literal HTTP listening port from the Node entrypoint. Clarify runtime configuration; no port is guessed.')
    if re.search(r'\.listen\([^\n]*[\'"](?:localhost|127\.0\.0\.1)[\'"]',source):
        raise ValueError('The Node server binds loopback inside the container; review its bind address.')
    return ['npm','run',name],int(next(iter(ports))),name
