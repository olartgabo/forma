"""Synthetic software fixtures only. No physical build or test was performed."""

from forma_renderer import ManualDiff, diff_manuals
from forma_renderer.svg import Manual, Panel
from test_stand_manual import build as build_fixture
from test_stand_manual import manual as render_fixture


def _panel(index: int, dependency_hash: str) -> Panel:
    return Panel(
        operation_id=f"op-{index}",
        part_ids=(),
        checkpoint_ids=(),
        dependency_hash=dependency_hash,
        svg="",
        tools=(),
    )


def _manual(hashes: tuple[str, ...], *, status: str = "accepted") -> Manual:
    return Manual(
        status=status,
        panels=tuple(_panel(index, value) for index, value in enumerate(hashes)),
        bill_of_materials=(),
        blockers=(),
    )


def _hashes(count: int) -> tuple[str, ...]:
    return tuple(f"hash-{index}" for index in range(count))


def test_identical_manuals_all_unchanged() -> None:
    old = _manual(_hashes(8))
    new = _manual(_hashes(8))
    diff = diff_manuals(old, new)
    assert diff == ManualDiff(
        unchanged=(0, 1, 2, 3, 4, 5, 6, 7),
        changed=(),
        added=(),
        removed=(),
    )
    assert diff.unchanged == (0, 1, 2, 3, 4, 5, 6, 7)
    assert diff.changed == ()
    assert diff.added == ()
    assert diff.removed == ()


def test_single_changed_position() -> None:
    old = _manual(_hashes(8))
    changed_hashes = tuple(
        "different-hash-3" if index == 3 else f"hash-{index}" for index in range(8)
    )
    new = _manual(changed_hashes)
    diff = diff_manuals(old, new)
    assert diff.unchanged == (0, 1, 2, 4, 5, 6, 7)
    assert diff.changed == (3,)
    assert diff.added == ()
    assert diff.removed == ()


def test_longer_new_manual_reports_added() -> None:
    old = _manual(_hashes(8))
    new = _manual(_hashes(8) + ("hash-8", "hash-9"))
    diff = diff_manuals(old, new)
    assert diff.unchanged == (0, 1, 2, 3, 4, 5, 6, 7)
    assert diff.changed == ()
    assert diff.added == (8, 9)
    assert diff.removed == ()


def test_shorter_new_manual_reports_removed() -> None:
    old = _manual(_hashes(8))
    new = _manual(_hashes(5))
    diff = diff_manuals(old, new)
    assert diff.unchanged == (0, 1, 2, 3, 4)
    assert diff.changed == ()
    assert diff.added == ()
    assert diff.removed == (5, 6, 7)


def test_empty_against_full() -> None:
    empty = _manual((), status="blocked")
    full = _manual(_hashes(8))
    added = diff_manuals(empty, full)
    assert added.unchanged == ()
    assert added.changed == ()
    assert added.added == (0, 1, 2, 3, 4, 5, 6, 7)
    assert added.removed == ()
    removed = diff_manuals(full, empty)
    assert removed.unchanged == ()
    assert removed.changed == ()
    assert removed.added == ()
    assert removed.removed == (0, 1, 2, 3, 4, 5, 6, 7)


def test_render_manual_twice_is_byte_identical_and_unchanged() -> None:
    plan, parameters, process = build_fixture()
    first = render_fixture(plan, parameters, process)
    second = render_fixture(plan, parameters, process)
    assert first.status == "accepted"
    assert second.status == "accepted"
    assert len(first.panels) == 8
    assert len(second.panels) == 8
    assert [panel.svg for panel in first.panels] == [
        panel.svg for panel in second.panels
    ]
    diff = diff_manuals(first, second)
    assert diff.unchanged == (0, 1, 2, 3, 4, 5, 6, 7)
    assert diff.changed == ()
    assert diff.added == ()
    assert diff.removed == ()
