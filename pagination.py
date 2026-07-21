"""Local pagination. Every function here operates on a Python list
already in memory — nothing in this module ever calls the API, so
Previous/Next/Jump-to-page are always instant and free. No page limit —
total_pages grows with however many jobs were fetched.
"""
import math


def total_pages(total_items: int, page_size: int) -> int:
    if total_items <= 0:
        return 0
    return math.ceil(total_items / page_size)


def page_slice(items: list, page_number: int, page_size: int) -> list:
    """Page 1 -> items[0:10], Page 2 -> items[10:20], and so on. Never
    skips or repeats items — Next always begins from the first unseen job.
    """
    start = (page_number - 1) * page_size
    end = start + page_size
    return items[start:end]


def page_range_text(page_number: int, page_size: int, total_items: int):
    start = (page_number - 1) * page_size + 1
    end = min(page_number * page_size, total_items)
    return start, end


def clamp_page(page_number: int, pages_count: int) -> int:
    if pages_count <= 0:
        return 1
    return max(1, min(page_number, pages_count))