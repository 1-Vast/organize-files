from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import tidy_audit  # noqa: E402


def kinds(result: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for item in result['findings']:
        out.setdefault(item['kind'], []).append(item['path'])
    return out


def write(path: Path, text: str = 'x') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def test_flags_messy_tree_and_leaves_it_unchanged(tmp_path: Path) -> None:
    write(tmp_path / 'README.md')
    write(tmp_path / 'report final.docx', 'a')
    write(tmp_path / 'report (1).docx', 'a')
    write(tmp_path / 'demo3.py', 'print(1)')
    write(tmp_path / 'Photo.JPG', 'p')
    write(tmp_path / 'notes 2024.3.5.md', 'n')
    write(tmp_path / 'Thumbs.db', 'j')
    write(tmp_path / 'pkg' / '__pycache__' / 'm.cpython-312.pyc', 'c')
    write(tmp_path / 'stages' / '1_load.py', '1')
    write(tmp_path / 'stages' / '10_plot.py', '10')
    write(tmp_path / 'wrap' / 'inner' / 'deep.txt', 'd')
    write(tmp_path / 'docx' / 'a.docx', 'z')
    write(tmp_path / 'mixed' / 'raw_counts.csv', 'counts')
    write(tmp_path / 'mixed' / 'raw-meta.csv', 'meta')
    (tmp_path / 'empty').mkdir()
    write(tmp_path / '.git' / 'HEAD', 'ref')
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*'))

    result = tidy_audit.audit(tmp_path, max_root_files=3)
    found = kinds(result)

    assert 'report (1).docx' in found['copy marker']
    assert 'report final.docx' in found['version marker']
    assert found['duplicate'] == ['report (1).docx']
    assert 'demo3.py' in found['vague name']
    assert found['extension case'] == ['Photo.JPG']
    assert found['date format'] == ['notes 2024.3.5.md']
    assert found['junk'] == ['Thumbs.db']
    assert found['cache'] == ['pkg/__pycache__']
    assert found['unpadded numbering'] == ['stages']
    assert found['single-child chain'] == ['wrap']
    assert found['format-named dir'] == ['docx']
    assert found['mixed naming'] == ['mixed']
    assert found['off-style name'] == ['mixed/raw-meta.csv', 'notes 2024.3.5.md']
    assert found['empty dir'] == ['empty']
    assert found['root clutter'] == ['.']
    assert result['opaque'] == ['.git']
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*')) == before


def test_clean_tree_and_numbered_series_have_no_findings(tmp_path: Path) -> None:
    write(tmp_path / 'README.md')
    write(tmp_path / 'main.py', 'run')
    for page in range(1, 21):
        write(tmp_path / 'figures' / 'paper_pages' / f'page_{page:02d}.png', str(page))
    write(tmp_path / 'figures' / 'overview.png', 'o')
    write(tmp_path / 'data' / 'raw' / 'counts.csv', 'c')
    write(tmp_path / 'data' / 'processed' / 'panel.csv', 'p')
    write(tmp_path / 'data' / 'processed' / 'medal_panel.csv', 'm')
    write(tmp_path / 'src' / 'load_data.py', 'l')

    result = tidy_audit.audit(tmp_path)

    assert result['findings'] == []
    assert result['counts']['files'] == 27


def test_tree_rendering_marks_opaque_dirs(tmp_path: Path) -> None:
    write(tmp_path / 'src' / 'app.py')
    write(tmp_path / '.venv' / 'lib' / 'x.py')
    lines = tidy_audit.tree(tmp_path)
    assert lines[0] == tmp_path.name + '/'
    assert any('.venv/  [1 files, not expanded]' in line for line in lines)
    assert any(line.endswith('app.py') for line in lines)
