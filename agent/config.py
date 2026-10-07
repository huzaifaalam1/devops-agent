"""Read agent credentials from its own .env, never from the inspected project."""
import os
from pathlib import Path
import re

ENV_FILE = Path(__file__).resolve().parents[1] / '.env'
PROVIDERS = {
    'openai': {'endpoint': 'https://api.openai.com/v1/responses', 'key': 'OPENAI_API_KEY', 'model': 'gpt-5.2'},
    'groq': {'endpoint': 'https://api.groq.com/openai/v1/responses', 'key': 'GROQ_API_KEY', 'model': 'openai/gpt-oss-120b'},
}
KEYS = {'OPENAI_API_KEY', 'GROQ_API_KEY', 'DEVOPS_AGENT_MODEL', 'DEVOPS_AGENT_PROVIDER'}


def settings():
    values = {}
    if ENV_FILE.exists():
        if not ENV_FILE.is_file() or ENV_FILE.stat().st_size > 64 * 1024:
            raise ValueError('Agent .env must be a text file smaller than 64 KiB.')
        for line in ENV_FILE.read_text().splitlines():
            match = re.fullmatch(r'\s*(?:export\s+)?(\w+)\s*=\s*(.*?)\s*', line)
            if not match or match[1] not in KEYS:
                continue
            value = match[2]
            if value.startswith(('"', "'")):
                quoted = re.fullmatch(r"(['\"])(.*?)\1\s*(?:#.*)?", value)
                if not quoted:
                    raise ValueError('Malformed quoted setting in agent .env.')
                value = quoted[2]
            else:
                value = re.split(r'\s+#', value, maxsplit=1)[0].strip()
            values[match[1]] = value
    # An explicitly exported value (even empty) takes precedence.
    values.update({key: os.environ[key] for key in KEYS if key in os.environ})
    provider = values.setdefault('DEVOPS_AGENT_PROVIDER', 'groq')
    if provider not in PROVIDERS:
        raise ValueError('DEVOPS_AGENT_PROVIDER must be groq or openai.')
    values.setdefault('DEVOPS_AGENT_MODEL', PROVIDERS[provider]['model'])
    return values
