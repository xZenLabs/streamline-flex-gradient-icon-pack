"""Run with python3 -m unittest discover -s scripts -p 'test_*.py'."""

import importlib.util
from io import BytesIO, StringIO
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, PngImagePlugin


spec = importlib.util.spec_from_file_location("builder", Path(__file__).with_name("build-zen-packs.py"))
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><path d="M0 0h48v48z"/></svg>'


class BuildPacksTest(unittest.TestCase):
    def test_streamline_flex_lookup_coverage_and_archive_contents(self):
        required = set("""
            library archive tab_folder tab_manga tab_news book.opened tab_history
            star.empty tab_collections tab_authors tab_series tab_translate tab_tags
            tab_to_be_read home appbar.search tab_stats tab_exit tab_left tab_right
            appbar.menu quicksettings controls more_vertical close close_light restart sleep
            battery_empty battery_low battery_half battery_high battery_full battery_charging
            quick_battery quick_bluetooth quick_incognito quick_localsend quick_lockdown
            quick_nightmode quick_puzzle quick_restart quick_rotate quick_screenshot
            quick_search quick_sleep quick_stats_calendar quick_stats_progress quick_sync
            quick_usb quick_wifi app_launcher appbar.settings appbar.tools appbar.typeset
            align.left align.right align.center align.justify wifi.open.0 wifi.open.100
            wifi.secure.0 wifi.secure.100 lookup.dictionary lookup.highlight quick_aa quick_streak
        """.split())
        # ZenPM's 39 bundled SVG names and 33 inline menu names (63 unique lookups).
        required.update("""
            allow_updates browser categories checkmark chevron.left chevron.right chevron.up
            clear close date debug details disable discover downgrade download downloads
            enable filter fonts games home icon_packs ignore_updates info kindleforge media
            open_box packages patch plugin productivity qrcode reference refresh reinstall
            remove remove_queue scan_plugins screensaver search settings settings_advanced
            settings_bug sort sort_asc sort_desc sources star star.filled sync_off theme
            title uninstall unverified update upgrade utility verified wallabag wallpaper zen zenpm
        """.split())
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            packs = list(builder.pack_sources(builder.ROOT, output))
            self.assertEqual([pack.name for pack, _ in packs], ["Streamline Flex Gradient"])
            pack, directories = packs[0]
            paths = [path for directory in directories for path in directory.glob("*.svg")]
            sources = {path.name: path for path in paths}
            self.assertEqual(len(sources), len(paths))
            self.assertEqual(len(sources), 141)
            self.assertFalse(list(pack.rglob("pack.lua")))
            metadata = json.loads((pack / "pack.json").read_text())
            self.assertEqual(metadata, json.loads((builder.ROOT / "pack.json").read_text()))
            self.assertIn("Streamline", metadata["author"])
            koreader = next(directory for directory in directories
                            if directory.name.startswith("KOReader Icons"))
            self.assertTrue({"appbar.menu", "appbar.search", "appbar.settings", "book.opened",
                             "wifi.open.100", "wifi.secure.100"}
                            <= {path.stem for path in koreader.glob("*.svg")})
            zen_paths = [path for path in paths if path.parent != koreader]
            self.assertEqual(len(zen_paths), len({path.read_bytes() for path in zen_paths}))
            destination = builder.build_pack(pack, directories, builder.ROOT,
                                             output, None, metadata)
            first_build = destination.read_bytes()
            builder.build_pack(pack, directories, builder.ROOT, output, None, metadata)
            self.assertEqual(destination.read_bytes(), first_build)
            with zipfile.ZipFile(destination) as archive:
                names = {Path(name).stem for name in archive.namelist() if name.endswith(".svg")}
                self.assertFalse(required - names, sorted(required - names))
                self.assertEqual(len(names), 246)
                self.assertFalse(any(name.endswith(".lua") for name in archive.namelist()))
                self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))
                prefix = destination.stem + "/"
                for name, path in sources.items():
                    self.assertEqual(archive.read(prefix + name), path.read_bytes())
                for target, source in builder.ALIASES.items():
                    if target + ".svg" not in sources and source in names:
                        self.assertEqual(archive.read(prefix + target + ".svg"),
                                         archive.read(prefix + source + ".svg"))
                self.assertEqual(json.loads(archive.read(prefix + "pack.json")), metadata)
                self.assertIn(b"Attribution 4.0 International", archive.read(prefix + "LICENSE-ICONS.txt"))
                battery_states = [archive.read(prefix + "battery_" + level + ".svg")
                                  for level in ("empty", "low", "half", "high", "full")]
                self.assertEqual(len(set(battery_states)), 5)
                for secure in ("open", "secure"):
                    wifi_states = [archive.read(prefix + "wifi." + secure + "." + str(level) + ".svg")
                                   for level in (0, 25, 50, 75, 100)]
                    self.assertEqual(len(set(wifi_states)), 5)
                self.assertIn(b"https://streamlinehq.com", archive.read(prefix + "LICENSE-ICONS.txt"))
                self.assertIsNone(archive.testzip())
            with patch("sys.argv", ["build-zen-packs.py", str(pack),
                                    "--output", str(output), "--version", "2.3.4"]):
                builder.main()
            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(json.loads(archive.read(prefix + "pack.json")),
                                 dict(metadata, version="2.3.4"))

    def test_streamline_flex_source_audit_matches_standalone_svgs(self):
        import csv
        import hashlib
        import xml.etree.ElementTree as ET

        with (builder.ROOT / "icon-sources.csv").open(newline="") as source:
            rows = list(csv.DictReader(source))
        sources = {path.name: path for path in (builder.ROOT / "Streamline Flex Gradient").rglob("*.svg")}
        self.assertEqual({row["filename"] for row in rows}, set(sources))
        self.assertEqual(len(rows), len(sources))
        for row in rows:
            data = sources[row["filename"]].read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"])
            self.assertIn("/streamline-vectors/blob/", row["source_url"])
            self.assertTrue(row["source_path"].startswith("flex/gradient/"))
            self.assertNotIn(b"currentColor", data)
            root = ET.fromstring(data)
            identifiers = [element.get("id") for element in root.iter() if element.get("id")]
            self.assertEqual(len(identifiers), len(set(identifiers)), row["filename"])
            import re
            references = set(re.findall(r"url\(#([^)]*)\)", data.decode()))
            self.assertTrue(references <= set(identifiers), row["filename"])
            for element in root.iter():
                self.assertNotIn(element.tag.rsplit("}", 1)[-1], {"script", "style", "image"})
                for key, value in element.attrib.items():
                    if key.rsplit("}", 1)[-1] == "href":
                        self.assertTrue(value.startswith("#"))

    def test_color_metadata_survives_repository_and_direct_builds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            manifest = {"version": "2.3.4", "author": "Repository artist", "color": True}
            (root / "pack.json").write_text(json.dumps(manifest))
            for name, color in (("Color", True), ("Mono", False)):
                pack = root / name
                icons = pack / "Pack Icons"
                icons.mkdir(parents=True)
                (icons / "home.svg").write_bytes(SVG)
                (pack / "pack.json").write_text(json.dumps(dict(manifest, color=color)))
            for source in (root, root / "Color", root / "Mono"):
                with self.subTest(source=source), patch("sys.argv", [
                        "build-zen-packs.py", str(source), "--output", str(output),
                        "--version", "3.4.5"]):
                    builder.main()
                    for pack, _ in builder.pack_sources(source, output):
                        pack_id = builder.zen_id(pack.name)
                        with zipfile.ZipFile(output / (pack_id + ".zip")) as archive:
                            metadata = json.loads(archive.read(pack_id + "/pack.json"))
                            self.assertIs(metadata["color"], pack.name == "Color")
                            self.assertEqual(metadata["version"], "3.4.5")
                            self.assertEqual(metadata["author"], "Repository artist")
            for manifest_path in (root / "pack.json", root / "Mono" / "pack.json"):
                for invalid in (None, "false", 0, 1, [], {}):
                    with self.subTest(manifest=manifest_path, color=invalid):
                        manifest_path.write_text(json.dumps(dict(manifest, color=invalid)))
                        with patch("sys.argv", ["build-zen-packs.py", str(root),
                                                "--output", str(output)]):
                            with patch("sys.stderr", new=StringIO()) as errors:
                                with self.assertRaises(SystemExit):
                                    builder.main()
                            self.assertIn("color must be a boolean", errors.getvalue())
                manifest_path.write_text(json.dumps(manifest))

    def test_repository_pack_json_metadata_and_cli_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pack, output = root / "Pack", root / "output"
            pack.mkdir()
            (pack / "sui_menu.svg").write_bytes(SVG)
            (pack / "pack.lua").write_text(
                'return { name = "Pack", version = "1.0.0", author = "Old artist", }')
            manifest = {"schema_version": 1, "id": "zen-example", "name": "Example for ZenOS",
                        "version": "2.3.4", "author": "Repository artist"}
            (root / "pack.json").write_text(json.dumps(manifest))
            for options, expected in (([], "2.3.4"), (["--version", "3.0.0"], "3.0.0")):
                with self.subTest(options=options), patch("sys.argv", [
                        "build-zen-packs.py", str(root), "--output", str(output), *options]):
                    builder.main()
                    with zipfile.ZipFile(output / "zen-pack.zip") as archive:
                        metadata = json.loads(archive.read("zen-pack/pack.json"))
                        self.assertEqual(metadata, dict(manifest, id="zen-pack",
                                                        name="Pack for ZenOS", version=expected))
            (pack / "pack.json").write_text(json.dumps(manifest))
            with patch("sys.argv", ["build-zen-packs.py", str(pack), "--output", str(output)]):
                builder.main()
            with zipfile.ZipFile(output / "zen-example.zip") as archive:
                self.assertEqual(json.loads(archive.read("zen-example/pack.json")), manifest)
            (pack / "pack.json").write_text(json.dumps(dict(manifest, id="../unsafe")))
            with patch("sys.argv", ["build-zen-packs.py", str(pack), "--output", str(output)]):
                with self.assertRaises(SystemExit), patch("sys.stderr"):
                    builder.main()

    def test_custom_png_map_strips_metadata_and_appended_zip_preserving_pixels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pack, output = root / "input", root / "output"
            pack.mkdir()
            output.mkdir()
            marker = root / "must-not-exist"
            (pack / "pack.lua").write_text(
                f'os.execute("touch {marker}")\n'
                'return { name = "Night Owl", author = "Test artist", version = "2.3.4",\n'
                'map = { ["sui_action_homescreen"] = "house image.png", sui_search = "lens.svg", }, }\n')
            (pack / "lens.svg").write_bytes(SVG)
            pixels = Image.new("RGBA", (2, 2), (12, 34, 56, 128))
            pixels.putpixel((1, 1), (200, 150, 100, 0))
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("payload", "metadata must be discarded")
            metadata.add(b"ruSt", b"hidden private chunk")
            original = BytesIO()
            pixels.save(original, format="PNG", pnginfo=metadata, icc_profile=b"fake ICC payload")
            appended = BytesIO()
            with zipfile.ZipFile(appended, "w") as archive:
                archive.writestr("hidden.lua", "untrusted appended file")
            source = original.getvalue() + appended.getvalue()
            (pack / "house image.png").write_bytes(source)

            destination = builder.build_pack(pack, [pack], pack, output, None)

            self.assertFalse(marker.exists())
            self.assertEqual((pack / "house image.png").read_bytes(), source)
            with zipfile.ZipFile(destination) as archive:
                prefix = "zen-night-owl/"
                manifest = json.loads(archive.read(prefix + "pack.json"))
                self.assertEqual(manifest["id"], "zen-night-owl")
                self.assertEqual(manifest["version"], "2.3.4")
                self.assertEqual(manifest["author"], "Test artist")
                self.assertEqual(archive.read(prefix + "appbar.search.svg"), SVG)
                clean = archive.read(prefix + "home.png")
                self.assertEqual(clean, archive.read(prefix + "house-image.png"))
                self.assertNotIn(prefix + "pack.lua", archive.namelist())
            with Image.open(BytesIO(clean)) as image:
                self.assertEqual(image.info, {})
                self.assertEqual(image.convert("RGBA").tobytes(), pixels.tobytes())
            offset, chunks = 8, []
            while offset < len(clean):
                size = struct.unpack_from(">I", clean, offset)[0]
                chunks.append(clean[offset + 4:offset + 8])
                offset += size + 12
            self.assertEqual(offset, len(clean))
            self.assertEqual(chunks, [b"IHDR", b"IDAT", b"IEND"])

    def test_flat_pack_without_manifest_uses_svg_and_png_slot_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "Minimal"
            output = Path(temporary) / "output"
            pack.mkdir()
            output.mkdir()
            (pack / "sui_menu.svg").write_bytes(SVG)
            Image.new("P", (1, 1)).save(pack / "sui_action_wifi_toggle.png")
            Image.new("RGBA", (1, 1)).save(pack / "HOME.PNG")
            self.assertEqual(list(builder.pack_sources(pack, output)), [(pack, [pack])])
            destination = builder.build_pack(pack, [pack], pack, output, "9.0")
            with zipfile.ZipFile(destination) as archive:
                self.assertIn("zen-minimal/appbar.menu.svg", archive.namelist())
                self.assertIn("zen-minimal/quick_wifi.png", archive.namelist())
                self.assertIn("zen-minimal/home.png", archive.namelist())
                self.assertNotIn("zen-minimal/HOME.png", archive.namelist())
                self.assertEqual(json.loads(archive.read("zen-minimal/pack.json"))["version"], "9.0")

    def test_bad_pngs_are_rejected_without_replacing_a_zip(self):
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "Broken"
            output = Path(temporary) / "output"
            pack.mkdir()
            output.mkdir()
            destination = output / "zen-broken.zip"
            destination.write_bytes(b"previous release")
            valid = BytesIO()
            Image.new("RGBA", (2, 2)).save(valid, format="PNG")
            animated = BytesIO()
            Image.new("RGBA", (2, 2), "red").save(
                animated, format="PNG", save_all=True,
                append_images=[Image.new("RGBA", (2, 2), "blue")])
            for name, data in {"empty": b"", "renamed SVG": SVG,
                               "truncated": valid.getvalue()[:24], "animated": animated.getvalue()}.items():
                with self.subTest(name=name):
                    (pack / "icon.png").write_bytes(data)
                    with self.assertRaises((ValueError, OSError, SyntaxError)):
                        builder.build_pack(pack, [pack], pack, output, None)
                    self.assertEqual(destination.read_bytes(), b"previous release")
            (pack / "icon.png").write_bytes(valid.getvalue())
            with patch.object(Image, "MAX_IMAGE_PIXELS", 3):
                with self.assertRaises(Image.DecompressionBombWarning):
                    builder.clean_icon(pack / "icon.png")

    def test_duplicates_missing_maps_and_symlinks_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / "Bad"
            output = Path(temporary) / "output"
            pack.mkdir()
            output.mkdir()
            (pack / "home.svg").write_bytes(SVG)
            second = pack / "second"
            second.mkdir()
            (second / "HOME.svg").write_bytes(SVG)
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                builder.build_pack(pack, [pack], pack, output, None)
            (second / "HOME.svg").unlink()
            (pack / "pack.lua").write_text('return { map = { sui_menu = "missing.svg", }, }')
            with self.assertRaisesRegex(ValueError, "missing mapped icon"):
                builder.build_pack(pack, [pack], pack, output, None)
            (pack / "pack.lua").unlink()
            (pack / "linked.svg").symlink_to(pack / "home.svg")
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                builder.build_pack(pack, [pack], pack, output, None)

    def test_discovers_mixed_variants_and_ignores_generated_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            named, plain, output = root / "Named", root / "Plain", root / "output"
            for directory in (named, plain, output):
                directory.mkdir()
                (directory / "sui_menu.svg").write_bytes(SVG)
            (named / "pack.lua").write_text('return { name = "Named", }')
            (output / "pack.lua").write_text('return { name = "Generated", }')
            self.assertEqual(list(builder.pack_sources(root, output)),
                             [(named, [named]), (plain, [plain])])
            (named / "pack.lua").write_text('return { name = computed_name(), }')
            with self.assertRaisesRegex(ValueError, "literal quoted string"):
                builder.lua_strings(named / "pack.lua")
            self.assertEqual(builder.zen_id("Lumière"), "zen-lumiere")
            self.assertRegex(builder.zen_id("夜猫"), r"^zen-[a-f0-9]{12}$")


if __name__ == "__main__":
    unittest.main()
