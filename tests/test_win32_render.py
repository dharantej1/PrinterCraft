import unittest

from printer_craft.backends.win32_render import (
    DeviceGeometry,
    PageSource,
    expand_page_ranges,
    layout_sheet,
    number_up_grid,
    plan_sheets,
    resolve_scaling,
    select_pages,
    sniff_bytes,
)
from printer_craft.exceptions import DocumentConversionError
from printer_craft.models import Orientation, PrintJobOptions, PrintScaling


class FakePage(PageSource):
    def __init__(self, w=612.0, h=792.0):
        self.size_pt = (w, h)


class TestPageSelection(unittest.TestCase):
    def test_expand_page_ranges(self):
        self.assertEqual(expand_page_ranges("1-3,5", 10), [1, 2, 3, 5])
        self.assertEqual(expand_page_ranges("8-", 10), [8, 9, 10])
        self.assertEqual(expand_page_ranges("-2", 10), [1, 2])
        self.assertEqual(expand_page_ranges("3,1,3", 10), [1, 3])
        self.assertEqual(expand_page_ranges("9-20", 10), [9, 10])
        with self.assertRaises(DocumentConversionError):
            expand_page_ranges("a-b", 10)

    def test_select_pages_matches_cups_semantics(self):
        self.assertEqual(select_pages(PrintJobOptions(), 3), [1, 2, 3])
        self.assertEqual(select_pages(PrintJobOptions(page_ranges="1,1,1,1"), 3), [1, 1, 1, 1])
        self.assertEqual(select_pages(PrintJobOptions(page_ranges="3,1"), 3), [3, 1])
        self.assertEqual(select_pages(PrintJobOptions(page_ranges="1,3"), 3), [1, 3])
        # repeat duplicates page 1, exactly like CUPSBackend's [1] * repeat
        self.assertEqual(select_pages(PrintJobOptions(repeat=3), 5), [1, 1, 1])
        # a repeated sequence takes precedence over repeat
        self.assertEqual(select_pages(PrintJobOptions(page_ranges="2,2", repeat=4), 3), [2, 2])
        # monotonic ranges with repeat apply to the repeated stream (lp -o page-ranges on the new PDF)
        self.assertEqual(select_pages(PrintJobOptions(page_ranges="2-3", repeat=4), 5), [1, 1])
        self.assertEqual(select_pages(PrintJobOptions(page_ranges="5,9,9"), 5), [5])


class TestLayout(unittest.TestCase):
    geom = DeviceGeometry(100, 100, 850, 1100, 850, 1100)

    def test_resolve_scaling(self):
        self.assertEqual(resolve_scaling(PrintJobOptions()), "fit")
        self.assertEqual(resolve_scaling(PrintJobOptions(fit_to_page=False)), "none")
        self.assertEqual(resolve_scaling(PrintJobOptions(fit_to_page=None)), "auto-fit")
        self.assertEqual(resolve_scaling(PrintJobOptions(scaling=PrintScaling.FILL)), "fill")
        self.assertEqual(resolve_scaling(PrintJobOptions(scaling=PrintScaling.NONE)), "none")
        self.assertEqual(resolve_scaling(PrintJobOptions(scaling=PrintScaling.AUTO)), "auto-fit")

    def test_number_up_grid(self):
        self.assertEqual(number_up_grid(2, False), (1, 2))
        self.assertEqual(number_up_grid(2, True), (2, 1))
        self.assertEqual(number_up_grid(6, False), (2, 3))
        self.assertEqual(number_up_grid(16, False), (4, 4))

    def test_landscape_page_auto_rotates_on_portrait_sheet(self):
        (p,) = layout_sheet([FakePage(792, 612)], self.geom, PrintJobOptions())
        self.assertEqual(p.rotation, 90)
        self.assertEqual(p.rect, (0, 0, 850, 1100))

    def test_explicit_orientation_disables_auto_rotate(self):
        (p,) = layout_sheet([FakePage(792, 612)], self.geom, PrintJobOptions(orientation=Orientation.PORTRAIT))
        self.assertEqual(p.rotation, 0)
        (p,) = layout_sheet([FakePage()], self.geom, PrintJobOptions(orientation=Orientation.REVERSE_PORTRAIT))
        self.assertEqual(p.rotation, 180)

    def test_fill_and_auto_fit(self):
        (p,) = layout_sheet([FakePage(612, 612)], self.geom, PrintJobOptions(scaling=PrintScaling.FILL))
        self.assertEqual(p.rect[3] - p.rect[1], 1100)
        big = FakePage(1224, 1584)
        (p,) = layout_sheet([big], self.geom, PrintJobOptions(scaling=PrintScaling.AUTO_FIT))
        self.assertEqual(p.rect, (0, 0, 850, 1100))
        (p,) = layout_sheet([FakePage(306, 396)], self.geom, PrintJobOptions(scaling=PrintScaling.AUTO_FIT))
        self.assertEqual(p.rect, (212, 275, 637, 825))

    def test_four_up_cells(self):
        placements = layout_sheet([FakePage()] * 4, self.geom, PrintJobOptions(number_up=4))
        self.assertEqual(len(placements), 4)
        for p in placements:
            self.assertLessEqual(p.rect[2] - p.rect[0], 425)
            self.assertLessEqual(p.rect[3] - p.rect[1], 550)

    def test_plan_sheets(self):
        pages = [FakePage() for _ in range(5)]
        self.assertEqual([len(s) for s in plan_sheets(pages, 2)], [2, 2, 1])
        self.assertEqual(len(plan_sheets(pages, 1, copies=2)), 10)
        self.assertEqual(len(plan_sheets(pages, 1, copies=2, duplex=True)), 12)
        uncollated = plan_sheets(pages[:2], 1, copies=2, collate=False)
        self.assertIs(uncollated[0][0], uncollated[1][0])


class TestSniff(unittest.TestCase):
    def test_sniff_bytes(self):
        self.assertEqual(sniff_bytes(b"%PDF-1.7"), "pdf")
        self.assertEqual(sniff_bytes(b"\x89PNG\r\n"), "image")
        self.assertEqual(sniff_bytes(b"\xff\xd8\xff\xe0"), "image")
        self.assertIsNone(sniff_bytes(b"%!PS-Adobe"))
        self.assertIsNone(sniff_bytes(b"\x1bE PCL"))


class TestPaperMatching(unittest.TestCase):
    def test_match_standard_paper_names(self):
        from printer_craft.backends.win32_render import match_standard_paper

        # Exact and within tolerance (0.25 mm ~ 0.71 pt)
        self.assertEqual(match_standard_paper(612.0, 792.0), "letter")
        self.assertEqual(match_standard_paper(792.0, 612.0), "letter")  # landscape
        self.assertEqual(match_standard_paper(595.28, 841.89), "a4")
        self.assertEqual(match_standard_paper(841.89, 595.28), "a4")
        self.assertEqual(match_standard_paper(841.89, 1190.55), "a3")
        self.assertEqual(match_standard_paper(1728.0, 2592.0), "arch_d")
        self.assertEqual(match_standard_paper(1584.0, 2448.0), "ansi_d")
        # Near match within 0.5 pt
        self.assertEqual(match_standard_paper(612.3, 791.8), "letter")
        # Non-matching custom size returns None
        self.assertIsNone(match_standard_paper(500.0, 500.0))


if __name__ == "__main__":
    unittest.main()
