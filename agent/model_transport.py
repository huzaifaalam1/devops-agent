"""One bounded request to the allowlisted provider endpoint; no redirects; retries are bounded by the caller."""
import multiprocessing
import json
import math
import re
from agent.config import PROVIDERS

ENDPOINT = 'https://api.openai.com/v1/responses'
MAX_RESPONSE_BYTES = 256 * 1024


def error_metadata(body, headers):
    """Return allowlisted categories/timing, never provider messages or identifiers."""
    result = {}
    try:
        error = json.loads(body).get('error', {})
        code = error.get('code')
        if code in ('rate_limit_exceeded', 'insufficient_quota', 'invalid_api_key', 'model_not_found', 'json_validate_failed', 'invalid_request_error', 'context_length_exceeded'):
            result['error_code'] = code
        kind = error.get('type')
        if kind in ('tokens', 'requests'):
            result['limit_type'] = kind
        if code != 'rate_limit_exceeded':
            return result
        retry = headers.get('retry-after')
        if retry is None:
            message = error.get('message', '')
            match = re.search(r'Please try again in ([0-9]+(?:\.[0-9]+)?)s', message) if isinstance(message, str) else None
            retry = match[1] if match else None
        if retry is not None:
            delay = float(retry)
            if math.isfinite(delay) and 0 <= delay <= 86400:
                result['retry_after_seconds'] = delay
    except (ValueError, TypeError, AttributeError):
        pass
    return result


def _worker(sender, payload, key, provider='openai'):
    import requests
    try:
        with requests.Session() as client:
            client.trust_env = False  # Never forward credentials through an env proxy.
            with client.post(PROVIDERS[provider]['endpoint'], json=payload,
                             headers={'Authorization': 'Bearer ' + key},
                             timeout=(5, 45), allow_redirects=False, stream=True) as response:
                body = bytearray()
                for chunk in response.iter_content(4096):
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        sender.send({'error': 'response_too_large'})
                        return
                if response.status_code != 200:
                    sender.send({'error': 'http_error', 'http_status': response.status_code,
                                 **error_metadata(bytes(body), response.headers)})
                else:
                    sender.send({'body': bytes(body).decode('utf-8')})
    except Exception:
        # Error bodies, request objects and exception text may contain credentials.
        try:
            sender.send({'error': 'connection_error'})
        except (OSError, EOFError):
            pass  # Parent already cancelled or timed out.
    finally:
        sender.close()


def request_once(payload, key, timeout=60, provider='openai'):
    """Terminate the worker on the overall deadline, including a slow response body."""
    if provider not in PROVIDERS:
        raise ValueError('Unsupported model provider.')
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(sender, payload, key, provider), daemon=True)
    try:
        process.start()
        sender.close()
        if not receiver.poll(timeout):
            return {'error': 'timeout'}
        return receiver.recv()
    except (OSError, EOFError):
        return {'error': 'transport_unavailable'}
    finally:
        sender.close()
        receiver.close()
        if process.pid:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
