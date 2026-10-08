"""Bounded stable npm-range selection; no network or repository code execution.

Supports numeric versions, x ranges, ^, ~, comparators, conjunctions and ||.
Prereleases, hyphen ranges and malformed expressions require clarification.
Intervals are half-open over stable (major, minor, patch) tuples.
"""
import re

ZERO = (0, 0, 0)


def intersect(left, right):
    result = []
    for lo, hi in left:
        for other_lo, other_hi in right:
            start = max(lo, other_lo)
            end = other_hi if hi is None else hi if other_hi is None else min(hi, other_hi)
            if end is None or start < end:
                result.append((start, end))
    return result


def atom(token):
    match = re.fullmatch(r'(>=|<=|>|<|=|\^|~)?v?([0-9xX*]+(?:\.[0-9xX*]+){0,2})', token)
    if not match:
        raise ValueError('Unsupported Node version range syntax.')
    op, raw = match.groups()
    parts = raw.split('.')
    nums = []
    wildcard = False
    for part in parts:
        if part in ('x', 'X', '*'):
            wildcard = True
        elif wildcard or not re.fullmatch(r'0|[1-9][0-9]{0,3}', part):
            raise ValueError('Invalid Node version component.')
        else:
            nums.append(int(part))
    n = len(nums)
    if not n:
        if op not in (None, '='):
            raise ValueError('Wildcard comparator is not supported.')
        return [(ZERO, None)]
    low = tuple(nums + [0] * (3 - n))
    upper = (low[0]+1, 0, 0) if n == 1 else (low[0], low[1]+1, 0) if n == 2 else (low[0], low[1], low[2]+1)
    if op in (None, '='):
        return [(low, upper)]
    if op == '>=':
        return [(low, None)]
    if op == '>':
        return [(upper, None)]
    if op == '<':
        return [(ZERO, low)]
    if op == '<=':
        return [(ZERO, upper)]
    if op == '~':
        return [(low, (low[0]+1, 0, 0) if n == 1 else (low[0], low[1]+1, 0))]
    if low[0] or n == 1:
        end = (low[0]+1, 0, 0)
    elif low[1] or n == 2:
        end = (0, low[1]+1, 0)
    else:
        end = (0, 0, low[2]+1)
    return [(low, end)]


def ranges(spec):
    if not isinstance(spec, str) or not spec.strip() or len(spec) > 200:
        raise ValueError('A bounded nonempty Node version string is required.')
    result = []
    for branch in spec.split('||'):
        branch = re.sub(r'(>=|<=|>|<|=|\^|~)\s+', r'\1', branch.strip())
        if not branch:
            raise ValueError('Empty Node range alternative.')
        current = [(ZERO, None)]
        for token in branch.split():
            current = intersect(current, atom(token))
        result.extend(current)
    return result


def contained(inner, outer):
    """Every version in each inner interval must be covered by the outer union."""
    for lo, hi in inner:
        cursor = lo
        for start, end in sorted(outer, key=lambda i: i[0]):
            if start > cursor:
                break
            if end is None:
                cursor = None
                break
            cursor = max(cursor, end)
            if hi is not None and cursor >= hi:
                break
        if cursor is not None and (hi is None or cursor < hi):
            return False
    return bool(inner)


def select_node(requirements):
    """Pick the lowest allowed stable line, narrowing to minor/patch as needed.

    This selects a compatible numeric tag, not a release-lifecycle recommendation
    or proof the Docker tag exists. Build and readiness checks establish usability.
    """
    allowed = [(ZERO, None)]
    for spec in requirements:
        allowed = intersect(allowed, ranges(spec))
    if not allowed:
        raise ValueError('Node requirements have no common stable version.')
    low = min(lo for lo, _ in allowed)
    if low[0] == 0:
        raise ValueError('Node requirement has no usable explicit major lower bound.')
    major, minor, patch = low
    candidates = [str(major), f'{major}.{minor}', f'{major}.{minor}.{patch}']
    for tag in candidates:
        if contained(ranges(tag), allowed):
            return tag
    raise ValueError('Cannot select a stable Node image from the requirements.')
