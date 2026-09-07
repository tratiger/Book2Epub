"""Unit tests for natural sorting utilities."""

from pathlib import Path

from book2epub.util.natural_sort import natural_sort


def test_natural_sort_basic_numbers() -> None:
    items = ["1.jpg", "10.jpg", "2.jpg"]
    expected = ["1.jpg", "2.jpg", "10.jpg"]
    assert natural_sort(items) == expected


def test_natural_sort_spec_example() -> None:
    # Example from M1 specification:
    # page1.jpg
    # page2.jpg
    # page02-alt.jpg
    # page10.jpg
    items = ["page10.jpg", "page02-alt.jpg", "page2.jpg", "page1.jpg"]
    expected = ["page1.jpg", "page2.jpg", "page02-alt.jpg", "page10.jpg"]
    assert natural_sort(items) == expected


def test_natural_sort_mixed_case_extensions() -> None:
    items = ["page1.JPG", "page2.jpeg", "page10.Png", "page0.tif"]
    expected = ["page0.tif", "page1.JPG", "page2.jpeg", "page10.Png"]
    assert natural_sort(items) == expected


def test_natural_sort_case_insensitivity_and_tie_breaker() -> None:
    items = ["Page1.jpg", "page1.jpg", "PAGE2.jpg", "page2.jpg"]
    sorted_items = natural_sort(items)
    # Case-insensitive grouping: page1 before page2
    assert sorted_items[0].lower() == "page1.jpg"
    assert sorted_items[1].lower() == "page1.jpg"
    assert sorted_items[2].lower() == "page2.jpg"
    assert sorted_items[3].lower() == "page2.jpg"


def test_natural_sort_path_objects() -> None:
    paths = [Path("d:/scan/p10.png"), Path("d:/scan/p2.png"), Path("d:/scan/p1.png")]
    sorted_paths = natural_sort(paths)
    assert [p.name for p in sorted_paths] == ["p1.png", "p2.png", "p10.png"]
