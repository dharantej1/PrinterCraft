import unittest
from printer_craft.models import (
    ColorMode,
    DuplexMode,
    Orientation,
    PrintJobOptions,
    PrintScaling,
)


class TestModels(unittest.TestCase):
    def test_duplex_mode_from_str(self):
        self.assertEqual(DuplexMode.from_str("one-sided"), DuplexMode.ONE_SIDED)
        self.assertEqual(DuplexMode.from_str("simplex"), DuplexMode.ONE_SIDED)
        self.assertEqual(DuplexMode.from_str("two-sided-long-edge"), DuplexMode.TWO_SIDED_LONG_EDGE)
        self.assertEqual(DuplexMode.from_str("duplex"), DuplexMode.TWO_SIDED_LONG_EDGE)
        self.assertEqual(DuplexMode.from_str("two-sided-short-edge"), DuplexMode.TWO_SIDED_SHORT_EDGE)
        self.assertEqual(DuplexMode.from_str("tumble"), DuplexMode.TWO_SIDED_SHORT_EDGE)

        with self.assertRaises(ValueError):
            DuplexMode.from_str("invalid")

    def test_color_mode_from_str(self):
        self.assertEqual(ColorMode.from_str("monochrome"), ColorMode.MONOCHROME)
        self.assertEqual(ColorMode.from_str("grayscale"), ColorMode.MONOCHROME)
        self.assertEqual(ColorMode.from_str("color"), ColorMode.COLOR)
        self.assertEqual(ColorMode.from_str("auto"), ColorMode.AUTO)

        with self.assertRaises(ValueError):
            ColorMode.from_str("ultra-color")

    def test_orientation_from_str(self):
        self.assertEqual(Orientation.from_str("portrait"), Orientation.PORTRAIT)
        self.assertEqual(Orientation.from_str("landscape"), Orientation.LANDSCAPE)
        self.assertEqual(Orientation.from_str("reverse-landscape"), Orientation.REVERSE_LANDSCAPE)
        self.assertEqual(Orientation.from_str("reverse-portrait"), Orientation.REVERSE_PORTRAIT)

    def test_build_lp_args_complete(self):
        opts = PrintJobOptions(
            printer="HP_LaserJet",
            copies=3,
            title="My Document",
            duplex=DuplexMode.TWO_SIDED_LONG_EDGE,
            collate=True,
            color_mode=ColorMode.MONOCHROME,
            media="A4",
            page_ranges="1-3,5",
            orientation=Orientation.LANDSCAPE,
            fit_to_page=True,
            scaling=PrintScaling.AUTO_FIT,
            number_up=2,
            raw_options={"InputSlot": "Manual", "Resolution": "600dpi"},
        )
        args = opts.build_lp_args()

        self.assertIn("-d", args)
        self.assertEqual(args[args.index("-d") + 1], "HP_LaserJet")
        self.assertIn("-n", args)
        self.assertEqual(args[args.index("-n") + 1], "3")
        self.assertIn("-t", args)
        self.assertEqual(args[args.index("-t") + 1], "My Document")
        self.assertIn("-o", args)

        # Check key-value options
        self.assertIn("sides=two-sided-long-edge", args)
        self.assertIn("collate=true", args)
        self.assertIn("print-color-mode=monochrome", args)
        self.assertIn("media=A4", args)
        self.assertIn("page-ranges=1-3,5", args)
        self.assertIn("orientation-requested=4", args)
        self.assertIn("fit-to-page=true", args)
        self.assertIn("print-scaling=auto-fit", args)
        self.assertIn("number-up=2", args)
        self.assertIn("InputSlot=Manual", args)
        self.assertIn("Resolution=600dpi", args)


if __name__ == "__main__":
    unittest.main()
