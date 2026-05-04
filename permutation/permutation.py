# pyright: reportMissingImports=false

import os
import time

import boto3
from boto3.dynamodb.conditions import Key


LUNKER_TABLE = os.environ.get('LUNKER_TABLE', 'lunker')
PERMUTATION_TABLE = os.environ.get('PERMUTATION_TABLE', 'permutation')
LUNKER_INDEX = os.environ.get('LUNKER_INDEX', 'pk-tk-index')
TTL_DAYS = int(os.environ.get('PERMUTATION_TTL_DAYS', '30'))

_DYNAMODB = boto3.resource('dynamodb')
_LUNKER = _DYNAMODB.Table(LUNKER_TABLE)
_PERMUTATION = _DYNAMODB.Table(PERMUTATION_TABLE)


# Simple keyboard neighborhood map for replacement/insertion strategies.
_QWERTY_NEIGHBORS = {
    'a': 'qwsz', 'b': 'vghn', 'c': 'xdfv', 'd': 'erfcxs', 'e': 'rdsw',
    'f': 'rtgvcd', 'g': 'tyhbvf', 'h': 'yujnbg', 'i': 'uojk', 'j': 'uikmnh',
    'k': 'iolmj', 'l': 'opk', 'm': 'njk', 'n': 'bhjm', 'o': 'pikl',
    'p': 'ol', 'q': 'wa', 'r': 'tfde', 's': 'wedxza', 't': 'ygfr',
    'u': 'yihj', 'v': 'cfgb', 'w': 'qase', 'x': 'zsdc', 'y': 'uhgt',
    'z': 'asx',
    '0': '9', '1': '2', '2': '13', '3': '24', '4': '35',
    '5': '46', '6': '57', '7': '68', '8': '79', '9': '80'
}


def _unique_slds_from_lunker_tk_index():
    slds = set()
    query_kwargs = {
        'IndexName': LUNKER_INDEX,
        'KeyConditionExpression': Key('pk').eq('LUNKER#') & Key('tk').begins_with('LUNKER#'),
        'ProjectionExpression': 'tk'
    }

    while True:
        response = _LUNKER.query(**query_kwargs)
        for item in response.get('Items', []):
            tk = item.get('tk', '')
            parts = tk.split('#')
            if len(parts) >= 3 and parts[1]:
                slds.add(parts[1].lower())

        last_key = response.get('LastEvaluatedKey')
        if not last_key:
            break
        query_kwargs['ExclusiveStartKey'] = last_key

    return sorted(slds)


def _homoglyph_permutations(sld):
    swaps = {
        'o': ['0'], '0': ['o'],
        'i': ['1', 'l'], '1': ['i', 'l'], 'l': ['1', 'i'],
        's': ['5'], '5': ['s'],
        'a': ['4'], '4': ['a'],
        'e': ['3'], '3': ['e'],
        'g': ['9'], '9': ['g']
    }
    out = set()
    chars = list(sld)
    for idx, char in enumerate(chars):
        for rep in swaps.get(char, []):
            candidate = chars.copy()
            candidate[idx] = rep
            out.add(''.join(candidate))
    return out


def _omission_permutations(sld):
    return {sld[:idx] + sld[idx + 1:] for idx in range(len(sld)) if len(sld) > 1}


def _repetition_permutations(sld):
    out = set()
    for idx, char in enumerate(sld):
        out.add(sld[:idx] + char + sld[idx:])
    return out


def _transposition_permutations(sld):
    out = set()
    for idx in range(len(sld) - 1):
        if sld[idx] != sld[idx + 1]:
            out.add(sld[:idx] + sld[idx + 1] + sld[idx] + sld[idx + 2:])
    return out


def _hyphenation_permutations(sld):
    out = set()
    for idx in range(1, len(sld)):
        out.add(sld[:idx] + '-' + sld[idx:])
    return out


def _replacement_permutations(sld):
    out = set()
    for idx, char in enumerate(sld):
        for neighbor in _QWERTY_NEIGHBORS.get(char, ''):
            out.add(sld[:idx] + neighbor + sld[idx + 1:])
    return out


def _insertion_permutations(sld):
    out = set()
    for idx, char in enumerate(sld):
        for neighbor in _QWERTY_NEIGHBORS.get(char, ''):
            out.add(sld[:idx] + neighbor + sld[idx:])
            out.add(sld[:idx + 1] + neighbor + sld[idx + 1:])
    return out


def _addition_permutations(sld):
    out = set()
    charset = 'abcdefghijklmnopqrstuvwxyz0123456789'
    for ch in charset:
        out.add(ch + sld)
        out.add(sld + ch)
    return out


def _bitsquatting_permutations(sld):
    out = set()
    bit_masks = (1, 2, 4, 8, 16, 32, 64)
    for idx, ch in enumerate(sld):
        code = ord(ch)
        for mask in bit_masks:
            flipped = chr(code ^ mask)
            if flipped.isalnum() or flipped == '-':
                out.add(sld[:idx] + flipped + sld[idx + 1:])
    return out


def _vowel_swap_permutations(sld):
    out = set()
    vowels = 'aeiou'
    for idx, ch in enumerate(sld):
        if ch in vowels:
            for rep in vowels:
                if rep != ch:
                    out.add(sld[:idx] + rep + sld[idx + 1:])
    return out


def _strategy_candidates(sld):
    if len(sld) < 5:
        # Keep short-SLD output conservative to limit false positives.
        return [
            ('homoglyph', _homoglyph_permutations(sld)),
            ('transposition', _transposition_permutations(sld))
        ]

    if len(sld) == 5:
        # Use a medium profile for length-5 SLDs to balance coverage and noise.
        return [
            ('homoglyph', _homoglyph_permutations(sld)),
            ('transposition', _transposition_permutations(sld)),
            ('replacement', _replacement_permutations(sld))
        ]

    return [
        ('homoglyph', _homoglyph_permutations(sld)),
        ('omission', _omission_permutations(sld)),
        ('repetition', _repetition_permutations(sld)),
        ('transposition', _transposition_permutations(sld)),
        ('hyphenation', _hyphenation_permutations(sld)),
        ('replacement', _replacement_permutations(sld)),
        ('insertion', _insertion_permutations(sld)),
        ('addition', _addition_permutations(sld)),
        ('bitsquatting', _bitsquatting_permutations(sld)),
        ('vowel_swap', _vowel_swap_permutations(sld))
    ]


def _log_permutation_stats(sld, strategy_sets, pre_filter_count, post_filter_count):
    strategy_counts = ', '.join(f'{name}:{len(values)}' for name, values in strategy_sets)
    print(
        f'PERMUTATION_STATS sld={sld} len={len(sld)} '
        f'strategy_counts={{{strategy_counts}}} '
        f'pre_filter={pre_filter_count} post_filter={post_filter_count}'
    )


def _recommended_permutations(sld):
    sld = sld.lower()
    strategy_sets = _strategy_candidates(sld)
    candidates = set()
    for _, values in strategy_sets:
        candidates.update(values)

    normalized = set()
    for candidate in candidates:
        if not candidate or len(candidate) < 2:
            continue

        lowered = candidate.lower()
        if sld in lowered:
            continue

        if all(ch.isalnum() or ch == '-' for ch in lowered):
            normalized.add(lowered)

    _log_permutation_stats(sld, strategy_sets, len(candidates), len(normalized))

    return sorted(normalized)


def _write_permutations(sld, permutations):
    ttl = int(time.time()) + (TTL_DAYS * 24 * 60 * 60)
    _PERMUTATION.put_item(
        Item={
            'pk': 'LUNKER#',
            'sk': f'LUNKER#{sld}#',
            'sld': sld,
            'perm': permutations,
            'count': len(permutations),
            'ttl': ttl
        }
    )


def _requested_slds(event):
    if not isinstance(event, dict):
        return []

    candidate = event.get('sld') or event.get('Status')
    if isinstance(candidate, str):
        normalized = candidate.strip().lower()
        if normalized:
            return [normalized]

    return []


def handler(event, _context):
    requested = _requested_slds(event)
    slds = requested or _unique_slds_from_lunker_tk_index()
    written = 0

    for sld in slds:
        perms = _recommended_permutations(sld)
        _write_permutations(sld, perms)
        written += 1

    return {
        'statusCode': 200,
        'body': {
            'mode': 'single' if requested else 'full',
            'sld_count': len(slds),
            'items_written': written
        }
    }
