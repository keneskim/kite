#!/usr/bin/env python3
"""Run the Kite CLI and compare the produced programs across backends."""

import argparse
import fnmatch
import http.client
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time


TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
BACKENDS = ("c", "js", "java", "unity", "web")


class TestFailure(Exception):
    pass


def utf8(data):
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def expect(label, actual, expected):
    if actual != expected:
        raise TestFailure(f"{label}: expected {expected!r}, got {actual!r}")


class Runner:
    def __init__(self, work, timeout, tools):
        self.timeout = timeout
        self.tools = tools
        self.env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                        LC_ALL="C", TMP=str(work), TEMP=str(work), TMPDIR=str(work),
                        DOTNET_CLI_HOME=str(work), DOTNET_CLI_TELEMETRY_OPTOUT="1",
                        DOTNET_NOLOGO="1", NUGET_PACKAGES=str(work / "packages"))

    def run(self, cmd, cwd, *, stdin=b"", code=0):
        try:
            proc = subprocess.run(cmd, cwd=cwd, env=self.env, input=stdin,
                                  capture_output=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise TestFailure(f"timed out after {self.timeout:g}s: {cmd!r}\n"
                              f"stdout={exc.stdout!r}\nstderr={exc.stderr!r}") from exc
        if proc.returncode != code:
            raise TestFailure(f"expected exit {code}, got {proc.returncode}: {cmd!r}\n"
                              f"stdout={proc.stdout.decode('utf-8', errors='replace')}\n"
                              f"stderr={proc.stderr.decode('utf-8', errors='replace')}")
        return proc

    def translate(self, case, backend, work, error=None):
        cmd = [sys.executable, "-B", str(ROOT / "kite.py"), case.name]
        suffix = {"c": ".c", "js": ".js", "java": ".java", "unity": ".cs"}[backend]
        cmd += ["-o", case.with_suffix(suffix).name] if backend == "c" else ["--" + backend]
        proc = self.run(cmd, work, code=1 if error else 0)
        expect("translator stdout", utf8(proc.stdout), "")
        stderr = utf8(proc.stderr)
        outputs = list(work.glob("*" + suffix))
        if error:
            message, line = error
            source_line = utf8(case.read_bytes()).splitlines()[line - 1]
            if not re.fullmatch(r"出错了：[^\n]*" + re.escape(message) + r"[^\n]*\n"
                                + re.escape(f"  第 {line} 行：{source_line}\n"), stderr):
                raise TestFailure(f"expected KiteError containing {message!r} on line {line}, got {stderr!r}")
            expect("outputs after failed translation", outputs, [])
            return None
        expect("generated file count", len(outputs), 1)
        if not re.fullmatch(r"(?:提醒：[^\n]*\n)*已生成 [^\n]*" + re.escape(outputs[0].name)
                            + r"(?:（[^\n]*）)?\n", stderr):
            raise TestFailure(f"unexpected translator stderr: {stderr!r}")
        return outputs[0]

    def compile_c(self, source, work, *extra_sources):
        target = work / ("program.exe" if os.name == "nt" else "program")
        if self.tools["cl"]:
            cmd = [self.tools["cl"], "/nologo", "/utf-8", "/std:c11", "/O2",
                   source.name, *extra_sources, "/Fe:" + target.name, "/link", "ws2_32.lib"]
        else:
            cmd = [self.tools["gcc"], "-O2", source.name, *extra_sources, "-o", target.name, "-lm"]
            if os.name == "nt":
                cmd += ["-lws2_32"]
        self.run(cmd, work)
        return target

    def native_binding(self, case, work):
        case.write_text('extern c fn scale(x: number) -> number = "host_test_scale"\np scale(7)\n', encoding="utf-8")
        source = self.translate(case, "c", work)
        helper = work / "helper.c"
        helper.write_text("double host_test_scale(double x) { return x * 2.5; }\n", encoding="ascii")
        if self.tools["gcc"]:
            cmd = [sys.executable, "-B", str(ROOT / "kite.py"), case.name,
                   "--run", "--link", helper.name, "-o", source.name]
        else:
            cmd = [str(self.compile_c(source, work, helper.name))]
        proc = self.run(cmd, work)
        expect("native binding output", utf8(proc.stdout), "17.5\n")
        if not self.tools["gcc"]:
            expect("native binding stderr", utf8(proc.stderr), "")

    def console(self, case, backend, work, stdin, stdout, stderr="", code=0):
        source = self.translate(case, backend, work)
        if backend == "c":
            cmd = [str(self.compile_c(source, work))]
        elif backend == "js":
            cmd = [self.tools["node"], source.name]
        else:
            self.run([self.tools["javac"], "-encoding", "UTF-8", "-d", ".", source.name], work)
            cmd = [self.tools["java"], "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8",
                   "-Dstderr.encoding=UTF-8", "-cp", ".", source.stem]
        proc = self.run(cmd, work, stdin=stdin, code=code)
        expect("program stdout", utf8(proc.stdout), stdout)
        expect("program stderr", utf8(proc.stderr), stderr)

    def unity(self, case, work, expected=None):
        source = self.translate(case, "unity", work)
        code = utf8(source.read_bytes())
        for fragment in (f"public class {source.stem} : MonoBehaviour", "void Start()", "void Update()"):
            if fragment not in code:
                raise TestFailure(f"missing Unity output fragment {fragment!r}")
        stub = "UnityStub.cs"
        stub_code = utf8((TESTS / stub).read_bytes())
        sources = [stub, source.name]
        if expected is not None:
            marker = "void Log(object o) {}"
            expect("Unity log stub marker count", stub_code.count(marker), 1)
            stub_code = stub_code.replace(marker, "void Log(object o) { System.Console.WriteLine(o); }")
            shutil.copyfile(TESTS / "UnityConsole.cs", work / "UnityConsole.cs")
            sources.append("UnityConsole.cs")
        (work / stub).write_text(stub_code, encoding="utf-8")

        dotnet = self.tools["dotnet"]
        csc, mcs = self.tools["csc"], self.tools["mcs"]
        if dotnet and self.run([dotnet, "--list-sdks"], work).stdout.strip():
            version = utf8(self.run([dotnet, "--version"], work).stdout).strip()
            major, minor, *_ = version.split(".")
            framework = f"net{major}.{minor}" if int(major) >= 5 else f"netcoreapp{major}.{minor}"
            target = "Library" if expected is None else "Exe"
            (work / "UnityTest.csproj").write_text(
                '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                f'<TargetFramework>{framework}</TargetFramework><OutputType>{target}</OutputType>'
                '</PropertyGroup></Project>', encoding="utf-8")
            config = work / "NuGet.Config"
            config.write_text('<configuration><packageSources><clear/></packageSources></configuration>',
                              encoding="utf-8")
            self.run([dotnet, "restore", "--configfile", config.name], work)
            self.run([dotnet, "build", "--no-restore", "--output", "build"], work)
            artifact = work / "build" / "UnityTest.dll"
            cmd = [dotnet, str(artifact), source.stem]
        elif csc or mcs:
            target = "library" if expected is None else "exe"
            artifact = work / ("UnityTest.dll" if expected is None else "UnityTest.exe")
            flags = (["/nologo", "/codepage:65001", "/reference:System.Numerics.dll", f"/target:{target}", f"/out:{artifact.name}"]
                     if csc else ["-r:System.Numerics.dll", f"-target:{target}", f"-out:{artifact.name}"])
            self.run([csc or mcs, *flags, *sources], work)
            if self.tools["mono"]:
                cmd = [self.tools["mono"], str(artifact), source.stem]
            elif os.name == "nt":
                cmd = [str(artifact), source.stem]
            else:
                cmd = None
        else:
            return "stub compile requires csc, mcs, or a .NET SDK"

        expect("Unity build output exists", artifact.is_file(), True)
        if expected is not None:
            if cmd is None:
                return "stub execution requires mono or a .NET SDK"
            proc = self.run(cmd, work)
            expect("Unity stdout", utf8(proc.stdout), expected)
            expect("Unity stderr", utf8(proc.stderr), "")
        return None

    def web(self, case, work):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        example = utf8((ROOT / "examples" / "web.kite").read_bytes())
        expect("web port marker count", example.count("serve(8099, page)"), 1)
        case.write_text(example.replace("serve(8099, page)", f"serve({port}, page)"), encoding="utf-8")
        program = self.compile_c(self.translate(case, "c", work), work)
        with (work / "web.stdout").open("w+b") as stdout, (work / "web.stderr").open("w+b") as stderr:
            proc = subprocess.Popen([str(program)], cwd=work, env=self.env,
                                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
            try:
                deadline = time.monotonic() + self.timeout
                while True:
                    if proc.poll() is not None:
                        stderr.seek(0)
                        raise TestFailure(f"server exited early ({proc.returncode}): {utf8(stderr.read())!r}")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TestFailure(f"HTTP request timed out after {self.timeout:g}s")
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=remaining)
                    try:
                        conn.request("GET", "/?km=10")
                        response = conn.getresponse()
                        expect("HTTP status", response.status, 200)
                        body = utf8(response.read())
                        break
                    except ConnectionRefusedError:
                        time.sleep(min(0.05, remaining))
                    finally:
                        conn.close()
                if "10 公里 = 6.214 英里" not in body:
                    raise TestFailure(f"unexpected HTML: {body!r}")
            finally:
                proc.kill()
                proc.wait(timeout=self.timeout)
            stdout.seek(0)
            stderr.seek(0)
            expect("server stdout", utf8(stdout.read()), f"界面已启动：http://localhost:{port}\n")
            expect("server stderr", utf8(stderr.read()), "")


# Runtime failures retain output already written before the bad num() call.
BAD_NUM = {
    "num_trailing_junk": '"12kg"',
    "num_hex": '"0x10"',
    "num_bad_exponent": '"1e+"',
    "num_overflow": '"1e309"',
    "num_nan": '"NaN"',
    "num_unicode_space": '"\N{NO-BREAK SPACE}1"',
}

# Assert the diagnostic text fragment, line number and exact source excerpt.
REJECT = {
    "array_alias": ("xs = [1, 2]\nys = xs\n", "数组变量只能用新建数组初始化", 2),
    "matrix_alias": ("m = [[1, 2]]\nother = m\n", "数组变量只能用新建数组初始化", 2),
    "row_alias": ("m = [[1, 2]]\nrow = m[1]\n", "数组变量只能用新建数组初始化", 2),
    "kite_error": ('p 1\np missing\n', "「missing」还没有定义", 2),
}


MODULE_EXAMPLE = ROOT / "examples" / "modules"
MODULE_OUTPUT = "kite: (2, 3)\nkite: (7, 3)\n"
RECORD_ARRAY_OUTPUT = (
    "point: 2\nends: 12, 4\ncopy: 12, 99; lengths: 2, 3\n"
    "empty slice: 1, only\nvisit: a, 12\nvisit: changed, 20\nvisit: new, 40\nlength: 3\n"
)
RECORD_PREFIX = "record Point\n    x: number\n"
RECORD_ARRAY_REJECT = {
    "record_array_mixed_scalar": (RECORD_PREFIX + 'xs = [Point(1), 2]\n', "数组元素", 3),
    "record_array_mixed_record": (RECORD_PREFIX + 'record Other\n    x: number\nxs = [Point(1), Other(2)]\n', "数组元素", 5),
    "record_array_element_type": (RECORD_PREFIX + 'xs = [Point(1)]\nxs[1] = 2\n', "数组元素", 4),
    "record_array_push_type": (RECORD_PREFIX + 'xs = [Point(1)]\nxs.push(2)\n', "push", 4),
    "record_array_parameter_type": (RECORD_PREFIX + 'fn value(xs: Point[]) -> number\n    ret xs[1].x\np value([2])\n', "参数", 5),
    "record_array_alias": (RECORD_PREFIX + 'xs = [Point(1)]\nys = xs\n', "数组变量只能用新建数组初始化", 4),
    "record_array_borrowed_push": (RECORD_PREFIX + 'fn append(xs: Point[])\n    xs.push(Point(2))\nxs = [Point(1)]\nappend(xs)\n', "不能对函数参数或矩阵行 push", 4),
    "record_array_return": (RECORD_PREFIX + 'fn make()\n    ret [Point(1)]\nxs = make()\n', "函数不能返回数组", 4),
    "record_array_return_annotation": (RECORD_PREFIX + 'fn make() -> Point[]\n    ret [Point(1)]\n', "函数不能返回数组", 3),
    "record_array_field": (RECORD_PREFIX + 'record Group\n    points: Point[]\n', "字段类型不能是数组", 4),
    "record_array_print": (RECORD_PREFIX + 'xs = [Point(1)]\np xs\n', "打印值", 4),
    "record_array_interpolation": (RECORD_PREFIX + 'xs = [Point(1)]\np "{xs}"\n', "插值", 4),
    "record_array_field_mutation": (RECORD_PREFIX + 'xs = [Point(1)]\nxs[1].x = 2\n', "记录字段不能直接修改", 4),
    "record_array_equality": (RECORD_PREFIX + 'xs = [Point(1)]\np xs == xs\n', "比较", 4),
    "record_array_sort": (RECORD_PREFIX + 'xs = [Point(1)]\nsort(xs)\n', "sort", 4),
    "record_array_join": (RECORD_PREFIX + 'xs = [Point(1)]\np join(xs, ",")\n', "join", 4),
    "record_array_matrix": (RECORD_PREFIX + 'xs = [[Point(1)]]\n', "二维", 3),
    "record_array_empty": ('xs = []\n', "空数组不支持", 1),
    "number_array_return": ('fn make()\n    ret [1, 2]\nxs = make()\n', "函数不能返回数组", 2),
}
RECORD_REJECT = {
    "record_field_type": ('record Point\n    x: number\np Point("oops").x\n', "字段「x」要数字", 3),
    "record_field_mutation": ('record Point\n    x: number\na = Point(2)\na.x = 3\n', "记录字段不能直接修改", 4),
    "record_field_cycle": ('record Point\n    x: Point\n', "记录字段不能递归", 1),
    "module_missing_symbol": ('use "dep.kite" as dep\np dep::missing()\n', "没有声明「missing」", 2),
    "module_cycle": ('use "dep.kite" as dep\np 1\n', "模块循环引用", 1),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", action="append", choices=BACKENDS,
                        help="repeat to select backends explicitly (default: all available)")
    parser.add_argument("--case", action="append", metavar="GLOB",
                        help="repeat to select cases by name")
    parser.add_argument("--timeout", type=float, default=30, metavar="SECONDS",
                        help="per-process and HTTP timeout (default: 30)")
    args = parser.parse_args()
    if not 0 < args.timeout < float("inf"):
        parser.error("--timeout must be positive and finite")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    tools = {name: shutil.which(name) for name in
             ("cl", "gcc", "node", "java", "javac", "csc", "mcs", "mono", "dotnet")}
    if os.name != "nt":
        tools["cl"] = None
    missing = {
        "c": None if tools["cl"] or tools["gcc"] else "gcc or a loaded MSVC environment",
        "js": None if tools["node"] else "node",
        "java": None if tools["java"] and tools["javac"] else "java and javac",
        "unity": None,
    }
    missing["web"] = missing["c"]
    fixtures = sorted((*TESTS.glob("*.kite"), *(TESTS / "cases").glob("*.kite")))
    passed = failed = skipped = 0
    with tempfile.TemporaryDirectory(prefix="kite-tests-") as temp:
        work = Path(temp)
        runner = Runner(work, args.timeout, tools)
        for backend in dict.fromkeys(args.backend or BACKENDS):
            if missing[backend]:
                status = "FAIL" if args.backend else "SKIP"
                print(f"{status} {backend}: requires {missing[backend]}")
                failed += bool(args.backend)
                skipped += not args.backend
                continue
            if backend in ("web", "unity"):
                names = ("web",) if backend == "web" else ("game", "unity_text", "loop_dynamic", "kite_error", "modules", "record_arrays", *RECORD_REJECT, *RECORD_ARRAY_REJECT, "native_binding")
            else:
                names = (*[p.stem for p in fixtures], *BAD_NUM, *REJECT, "modules", "record_arrays", *RECORD_REJECT, *RECORD_ARRAY_REJECT, "native_binding")
            for name in names:
                if args.case and not any(fnmatch.fnmatchcase(name, pat) for pat in args.case):
                    continue
                case_dir = work / backend / name
                case_dir.mkdir(parents=True)
                case = case_dir / (name + ".kite")
                label = f"{backend}/{name}"
                try:
                    if name in ("modules", "record_arrays"):
                        example = "main.kite" if name == "modules" else "record_arrays.kite"
                        expected = MODULE_OUTPUT if name == "modules" else RECORD_ARRAY_OUTPUT
                        shutil.copyfile(MODULE_EXAMPLE / example, case)
                        shutil.copyfile(MODULE_EXAMPLE / "geo.kite", case_dir / "geo.kite")
                        if backend == "unity":
                            reason = runner.unity(case, case_dir, expected)
                            if reason:
                                print(f"SKIP {label}: {reason} (translation passed)")
                                skipped += 1
                                continue
                        else:
                            runner.console(case, backend, case_dir, b"", expected)
                    elif name == "native_binding":
                        if backend == "c":
                            runner.native_binding(case, case_dir)
                        else:
                            case.write_text('extern c fn scale(x: number) -> number = "host_scale"\n', encoding="utf-8")
                            runner.translate(case, backend, case_dir, error=("不支持 extern c", 1))
                    elif name in RECORD_REJECT:
                        text, message, line = RECORD_REJECT[name]
                        case.write_text(text, encoding="utf-8")
                        if name == "module_cycle":
                            # A self-cycle is reported on the entry's own import line.
                            case.write_text(text.replace('dep.kite', case.name), encoding="utf-8")
                        else:
                            (case_dir / "dep.kite").write_text("fn answer()\n    ret 42\n", encoding="utf-8-sig")
                        runner.translate(case, backend, case_dir, error=(message, line))
                    elif name in RECORD_ARRAY_REJECT:
                        text, message, line = RECORD_ARRAY_REJECT[name]
                        case.write_text(text, encoding="utf-8")
                        runner.translate(case, backend, case_dir, error=(message, line))
                    elif name in REJECT:
                        text, message, line = REJECT[name]
                        case.write_text(text, encoding="utf-8")
                        runner.translate(case, backend, case_dir, error=(message, line))
                    elif backend == "web":
                        runner.web(case, case_dir)
                    elif backend == "unity":
                        fixture = (ROOT / "unity" / "game.kite" if name == "game" else
                                   TESTS / "cases" / (name + ".kite"))
                        shutil.copyfile(fixture, case)
                        expected = None if name == "game" else utf8(fixture.with_suffix(".out").read_bytes())
                        reason = runner.unity(case, case_dir, expected)
                        if reason:
                            print(f"SKIP {label}: {reason} (translation passed)")
                            skipped += 1
                            continue
                    elif name in BAD_NUM:
                        case.write_text(f'p "before"\np num({BAD_NUM[name]})\np "after"\n', encoding="utf-8")
                        runner.console(case, backend, case_dir, b"", "before\n",
                                       "出错了：第 2 行：不能转成数字\n", 1)
                    else:
                        fixture = next(p for p in fixtures if p.stem == name)
                        shutil.copyfile(fixture, case)
                        stdin_path = fixture.with_suffix(".in")
                        stdin = stdin_path.read_bytes() if stdin_path.is_file() else b""
                        expected = utf8(fixture.with_suffix(".out").read_bytes())
                        if name == "bounds":
                            runner.console(case, backend, case_dir, stdin, "", expected, 1)
                        else:
                            runner.console(case, backend, case_dir, stdin, expected)
                except (TestFailure, OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
                    print(f"FAIL {label}\n  {exc}")
                    failed += 1
                else:
                    print(f"ok   {label}")
                    passed += 1
    print(f"{passed} passed, {failed} failed, {skipped} skipped")
    return int(failed != 0 or passed == 0)


if __name__ == "__main__":
    sys.exit(main())
