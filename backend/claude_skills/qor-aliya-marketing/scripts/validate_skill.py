#!/usr/bin/env python3
from pathlib import Path
import re, sys
p=Path(__file__).resolve().parents[1]
s=(p/'SKILL.md').read_text(encoding='utf-8')
assert s.startswith('---\nname: qor-') and s.count('---')>=2
assert len(list((p/'tests/scenarios.md').read_text().split('### ')))-1 >= 25
for f in p.rglob('*.md'):
    assert f.stat().st_size > 50, f'empty/short section: {f}'
print('Skill package structure OK (static checks only)')
