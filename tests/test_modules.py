"""Focused module loader tests (python -m unittest discover -s kite/tests)."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kite
from kite_modules import load_program


class ModuleTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def write(self, path, source, *, encoding="utf-8"):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding=encoding)
        return target

    def load(self, source):
        return load_program(source, self.root / "main.kite")

    def test_shared_dependency_and_record_annotations(self):
        shared = self.write("lib/shared.kite", "record Pair\n    x: number\n\n"
                            "fn pair(x: number) -> Pair\n    ret Pair(x)\n", encoding="utf-8-sig")
        self.write("lib/consumer.kite", 'use "shared.kite" as s\n'
                   "fn value(p0: s::Pair) -> number\n    ret p0.x\n")
        block = self.load('use "lib/consumer.kite" as c\n'
                          'use "lib/../lib/shared.kite" as s\n'
                          'use "lib/shared.kite" as another\n'
                          'p "{c::value(s::pair(3))}", another::pair(4).x\n')
        record, pair, consumer, entry = block.stmts
        self.assertIsInstance(record, kite.RecordDef)
        self.assertEqual(record.name, pair.ret)
        self.assertEqual(record.name, consumer.params[0][1])
        self.assertEqual(pair.source_path, str(shared))
        self.assertEqual(pair.name, entry.exprs[1].target.callee.id)
        kite.Typer(block).run()

    def test_qualified_record_array_annotations(self):
        self.write("lib/points.kite", "record Point\n    x: number\n")
        self.write("lib/read.kite", 'use "points.kite" as geo\n'
                   "fn first(points: geo::Point[]) -> number\n    ret points[1].x\n")
        block = self.load('use "lib/points.kite" as geo\n'
                          'use "lib/./points.kite" as same\n'
                          'use "lib/read.kite" as read\n'
                          'fn local(points: geo::Point[]) -> number\n    ret points[1].x\n'
                          'points = [geo::Point(1), same::Point(2)]\n'
                          'p read::first(points), local(points)\n')
        # The canonical module identity must survive the [] annotation suffix,
        # including when the same file is imported with two aliases.
        kite.Typer(block).run()

    def test_cycle_reports_file_and_chain(self):
        self.write("main.kite", "")
        other = self.write("lib/one.kite", 'use "../main.kite" as entry\n')
        with self.assertRaises(kite.KiteError) as caught:
            self.load('use "lib/one.kite" as one\n')
        self.assertEqual(caught.exception.path, str(other))
        self.assertEqual(caught.exception.line, 1)
        self.assertIn("main.kite", caught.exception.msg)
        self.assertIn("one.kite", caught.exception.msg)

    def test_rejects_executable_module_and_nonleading_use(self):
        other = self.write("lib.kite", "p 3\n")
        with self.assertRaises(kite.KiteError) as caught:
            self.load('use "lib.kite" as lib\n')
        self.assertEqual(caught.exception.path, str(other))
        self.assertEqual(caught.exception.line, 1)
        with self.assertRaises(kite.KiteError) as caught:
            self.load('fn sample()\n    use "lib.kite" as lib\n')
        self.assertEqual(caught.exception.line, 2)
        kite.Typer(self.load("use = 2\np use\n")).run()

    def test_module_cannot_capture_entry_function_or_record(self):
        standalone = 'use "lib.kite" as lib\nfn missing() -> number\n    ret 1\n'
        record_src = 'use "lib.kite" as lib\nrecord Hidden\n    x: number\n'
        for module_src, entry_src in [
            ("fn f() -> number\n    ret missing()\n", standalone),
            ("fn f(x: Hidden) -> number\n    ret 1\n", record_src),
        ]:
            with self.subTest(module=module_src):
                other = self.write("lib.kite", module_src)
                with self.assertRaises(kite.KiteError) as caught:
                    self.load(entry_src)
                self.assertEqual(caught.exception.path, str(other))

    def test_module_local_may_match_entry_function(self):
        self.write("lib.kite", "fn f(count: number) -> number\n    ret count\n")
        block = self.load('use "lib.kite" as lib\n'
                          'fn count() -> number\n    ret 1\np lib::f(3)\n')
        kite.Typer(block).run()

    def test_duplicate_alias_and_missing_export(self):
        self.write("lib.kite", "fn found() -> number\n    ret 1\n")
        for source, expected in [
            ('use "lib.kite" as lib\nuse "lib.kite" as lib\n', "lib"),
            ('use "lib.kite" as lib\np lib::missing()\n', "missing"),
        ]:
            with self.subTest(source=source):
                with self.assertRaises(kite.KiteError) as caught:
                    self.load(source)
                self.assertEqual(caught.exception.path, str(self.root / "main.kite"))
                self.assertEqual(caught.exception.line, 2)
                self.assertIn(expected, caught.exception.msg)

    def test_extern_keeps_native_symbol(self):
        self.write("lib.kite", 'extern c fn f(x: number) -> number = "native_f"\n')
        declaration, entry = self.load('use "lib.kite" as lib\np lib::f(3)\n').stmts
        self.assertIsInstance(declaration, kite.ExternDef)
        self.assertEqual(declaration.symbol, "native_f")
        self.assertEqual(declaration.name, entry.exprs[0].callee.id)

    def test_typing_error_reports_imported_file(self):
        other = self.write("lib.kite", "fn f(x: number) -> number\n    if x\n        ret 1\n")
        with self.assertRaises(kite.KiteError) as caught:
            kite.Typer(self.load('use "lib.kite" as lib\n')).run()
        self.assertEqual(caught.exception.path, str(other))
        self.assertEqual(caught.exception.line, 1)
        self.assertIn("ret", caught.exception.msg)


if __name__ == "__main__":
    unittest.main()
