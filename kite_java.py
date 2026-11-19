#!/usr/bin/env python3
"""
kite → Java。

    python3 kite.py 程序.kite --java
    javac 程序.java && java 程序
"""

import os
import sys

from kite import (
    load_program, require_backend, Typer, KiteError,
    Num, Text, Interp, Name, ListLit, BinOp, Unary, Call, Field, Index, Slice,
    Assign, Say, If, Loop, FnDef, RecordDef, Return, Break, Continue, ExprStmt,
    NUM, STR, VOID, elem_of, is_matrix, type_cn,
)

def java_name(name, function=False, record=False):
    prefix = "kite_record" if record else "kite_fn" if function else "kite_var"
    if name.isascii() and name.isidentifier():
        return prefix + "_" + name
    return prefix + "u_" + name.encode("utf-8").hex()


def cs(t):
    if t == NUM:
        return "double"
    if t == STR:
        return "String"
    if t == NUM + "[]":
        return "ArrayList<Double>"
    if t == STR + "[]":
        return "ArrayList<String>"
    if t == NUM + "[][]":
        return "ArrayList<ArrayList<Double>>"
    if t == STR + "[][]":
        return "ArrayList<ArrayList<String>>"
    if t == VOID:
        return "void"
    raise KiteError("Java 版还不支持%s" % type_cn(t))


PRELUDE = r'''
    // ---------------- kite 运行时 ----------------

    static void fail(String msg, int line) {
        throw new RuntimeException("第 " + line + " 行：" + msg);
    }

    static int index(double i, int n, int line) {
        if (!Double.isFinite(i)) fail("下标要是有限数字", line);
        double k = i < 0 ? Math.ceil(i) : Math.floor(i);
        if (k == 0) fail("下标从 1 开始数，没有第 0 个", line);
        if (k < 0) k = n + k + 1;
        if (k < 1 || k > n) fail("越界（下标 " + num2str(i) + "，长度 " + n + "，从 1 开始数）", line);
        return (int) k - 1;
    }

    static <T> T getList(ArrayList<T> a, double i, int line) {
        return a.get(index(i, a.size(), line));
    }
    static double getNum(ArrayList<Double> a, double i, int line) {
        return getList(a, i, line);
    }

    static <T> void setList(ArrayList<T> a, double i, T v, int line) {
        a.set(index(i, a.size(), line), v);
    }
    static void setNum(ArrayList<Double> a, double i, double v, int line) {
        setList(a, i, v, line);
    }

    static int[] sliceRange(double f, double t, int n, int line) {
        if (!Double.isFinite(f) || !Double.isFinite(t)) fail("切片下标要是有限数字", line);
        double from = f < 0 ? Math.ceil(f) : Math.floor(f);
        double to = t < 0 ? Math.ceil(t) : Math.floor(t);
        if (from < 0) from = n + from + 1;
        if (to < 0) to = n + to + 1;
        from = Math.max(1, Math.min((double) n + 1, from));
        to = Math.max(0, Math.min(n, to));
        if (from > to) return new int[]{0, 0};
        return new int[]{(int) from - 1, (int) to};
    }
    static <T> ArrayList<T> sliceList(ArrayList<T> a, double f, double t, int line) {
        int[] r = sliceRange(f, t, a.size(), line);
        return new ArrayList<>(a.subList(r[0], r[1]));
    }
    static String sliceStr(String s, double f, double t, int line) {
        int[] r = sliceRange(f, t, (int) len(s), line);
        return s.substring(s.offsetByCodePoints(0, r[0]), s.offsetByCodePoints(0, r[1]));
    }

    static ArrayList<Double> arr(double... v) {
        ArrayList<Double> a = new ArrayList<>();
        for (double x : v) a.add(x);
        return a;
    }
    static ArrayList<String> arrs(String... v) {
        ArrayList<String> a = new ArrayList<>();
        for (String x : v) a.add(x);
        return a;
    }
    static ArrayList<ArrayList<Double>> arr2(double[][] m) {
        ArrayList<ArrayList<Double>> a = new ArrayList<>();
        for (double[] row : m) {
            ArrayList<Double> r = new ArrayList<>();
            for (double x : row) r.add(x);
            a.add(r);
        }
        return a;
    }
    static ArrayList<ArrayList<String>> arr2s(String[][] m) {
        ArrayList<ArrayList<String>> a = new ArrayList<>();
        for (String[] row : m) {
            ArrayList<String> r = new ArrayList<>();
            for (String x : row) r.add(x);
            a.add(r);
        }
        return a;
    }

    static void checkMat(double rows, double cols, int line) {
        if (!Double.isFinite(rows) || !Double.isFinite(cols) || rows < 1 || cols < 1 ||
            (long)(int) rows * (int) cols > 10000000) fail("mat 的尺寸不合理", line);
    }

    static ArrayList<ArrayList<Double>> mat(double rows, double cols, double fill, int line) {
        checkMat(rows, cols, line);
        int r = (int) rows, c = (int) cols;
        ArrayList<ArrayList<Double>> a = new ArrayList<>();
        for (int i = 0; i < r; i++) {
            ArrayList<Double> row = new ArrayList<>();
            for (int j = 0; j < c; j++) row.add(fill);
            a.add(row);
        }
        return a;
    }
    static ArrayList<ArrayList<String>> mat(double rows, double cols, String fill, int line) {
        checkMat(rows, cols, line);
        int r = (int) rows, c = (int) cols;
        ArrayList<ArrayList<String>> a = new ArrayList<>();
        for (int i = 0; i < r; i++) {
            ArrayList<String> row = new ArrayList<>();
            for (int j = 0; j < c; j++) row.add(fill);
            a.add(row);
        }
        return a;
    }

    static double B(boolean v) { return v ? 1.0 : 0.0; }

    static final java.math.MathContext FORMAT_PRECISION = new java.math.MathContext(15, java.math.RoundingMode.HALF_EVEN);

    static String num2str(double v) {
        if (Double.isNaN(v)) return "nan";
        if (Double.isInfinite(v)) return v < 0 ? "-inf" : "inf";
        if (v == Math.rint(v) && Math.abs(v) < 1e15) return String.valueOf((long) v);
        java.math.BigDecimal rounded = new java.math.BigDecimal(v, FORMAT_PRECISION).stripTrailingZeros();
        int exponent = rounded.precision() - rounded.scale() - 1;
        if (exponent >= -4 && exponent < 15) return rounded.toPlainString();
        return rounded.scaleByPowerOfTen(-exponent).toPlainString() + "e" + exponent;
    }

    static double nextCount(double v, double step) {
        double next = v + step;
        return next == v ? Double.NaN : next;
    }

    static String S(double v) { return num2str(v); }
    static String S(String v) { return v; }
    static String S(ArrayList<?> a) { return show(a); }

    static String show(Object o) {
        if (o instanceof ArrayList) {
            StringBuilder sb = new StringBuilder("[");
            ArrayList<?> a = (ArrayList<?>) o;
            for (int i = 0; i < a.size(); i++) {
                if (i > 0) sb.append(", ");
                Object x = a.get(i);
                if (x instanceof String) sb.append(quote((String) x));
                else if (x instanceof Double) sb.append(num2str((Double) x));
                else sb.append(show(x));
            }
            sb.append("]");
            return sb.toString();
        }
        if (o instanceof String) return (String) o;
        if (o instanceof Double) return num2str((Double) o);
        return String.valueOf(o);
    }

    static String quote(String s) {
        StringBuilder out = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': out.append("\\\""); break;
                case '\\': out.append("\\\\"); break;
                case '\n': out.append("\\n"); break;
                case '\r': out.append("\\r"); break;
                case '\t': out.append("\\t"); break;
                case '\b': out.append("\\b"); break;
                case '\f': out.append("\\f"); break;
                default:
                    if (c < 32) out.append("\\u00").append(Character.forDigit(c >> 4, 16)).append(Character.forDigit(c & 15, 16));
                    else out.append(c);
            }
        }
        return out.append('"').toString();
    }

    // ---- 随机数：和 C 版同一套 64 位 xorshift ----
    static long rng = 0;

    static void seed(double s) {
        rng = (long) s * 6364136223846793005L + 1442695040888963407L;
        if (rng == 0) rng = 88172645463325252L;
    }

    static long nextRandom() {
        long x = rng;
        x ^= x << 13;
        x ^= x >>> 7;
        x ^= x << 17;
        rng = x;
        return x;
    }

    static double rand(double n) {
        if (rng == 0) { seed(System.currentTimeMillis() / 1000); nextRandom(); }
        long m = (long) n;
        if (m <= 0) return 0;
        return Long.remainderUnsigned(nextRandom(), m);
    }

    // ---- 输入输出 ----
    static final java.nio.charset.Charset UTF8 = java.nio.charset.StandardCharsets.UTF_8;
    static final java.io.PrintStream out = new java.io.PrintStream(System.out, true, UTF8);
    static final java.io.PrintStream err = new java.io.PrintStream(System.err, true, UTF8);
    static final java.io.BufferedReader in = new java.io.BufferedReader(new java.io.InputStreamReader(System.in, UTF8));

    static String ask(String prompt) {
        if (!prompt.isEmpty()) {
            out.print(prompt);
            out.flush();
        }
        try {
            String value = in.readLine();
            return value == null ? "" : value;
        } catch (java.io.IOException e) {
            fail("读不了标准输入：" + e.getMessage(), 0);
            return "";
        }
    }

    static String read(String path) {
        try {
            return new String(java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(path)),
                              java.nio.charset.StandardCharsets.UTF_8);
        } catch (Exception e) { return ""; }
    }

    static void write(String path, String s) {
        try {
            java.nio.file.Files.write(java.nio.file.Paths.get(path),
                s.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        } catch (Exception e) { fail("写不了文件：" + path, 0); }
    }

    static double exist(String path) {
        return java.nio.file.Files.exists(java.nio.file.Paths.get(path)) ? 1 : 0;
    }

    static void del(String path) {
        try { java.nio.file.Files.deleteIfExists(java.nio.file.Paths.get(path)); } catch (Exception e) {}
    }

    // ---- 内置 ----
    static double len(String s) { return s.codePointCount(0, s.length()); }
    static double lenList(ArrayList<?> a) { return a.size(); }

    static String txt(double v) { return num2str(v); }
    static String txt(String v) { return v; }
    static String txt(ArrayList<?> a) { return show(a); }

    static final java.util.regex.Pattern DECIMAL = java.util.regex.Pattern.compile(
        "[+-]?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)(?:[eE][+-]?[0-9]+)?");

    static double num(String s, int line) {
        s = s.replaceAll("^[\\t\\n\\x0b\\f\\r ]+|[\\t\\n\\x0b\\f\\r ]+\\z", "");
        if (s.isEmpty()) return 0;
        if (DECIMAL.matcher(s).matches()) {
            double v = Double.parseDouble(s);
            if (Double.isFinite(v)) return v;
        }
        fail("不能转成数字", line);
        return 0;
    }
    static String up(String s) { return s.toUpperCase(); }
    static String low(String s) { return s.toLowerCase(); }
    static String trim(String s) { return s.trim(); }

    static double sum(ArrayList<Double> a) { double s = 0; for (double v : a) s += v; return s; }
    static double avg(ArrayList<Double> a) { return a.isEmpty() ? 0 : sum(a) / a.size(); }
    static double max(ArrayList<Double> a) { double m = a.isEmpty() ? 0 : a.get(0); for (double v : a) if (v > m) m = v; return m; }
    static double min(ArrayList<Double> a) { double m = a.isEmpty() ? 0 : a.get(0); for (double v : a) if (v < m) m = v; return m; }

    static void sortNum(ArrayList<Double> a) { java.util.Collections.sort(a); }
    static void sortStr(ArrayList<String> a) { java.util.Collections.sort(a); }

    static String joinNum(ArrayList<Double> a, String sep) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < a.size(); i++) {
            if (i > 0) sb.append(sep);
            sb.append(num2str(a.get(i)));
        }
        return sb.toString();
    }
    static String joinStr(ArrayList<String> a, String sep) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < a.size(); i++) {
            if (i > 0) sb.append(sep);
            sb.append(a.get(i));
        }
        return sb.toString();
    }

    static ArrayList<String> split(String s, String sep) {
        ArrayList<String> a = new ArrayList<>();
        if (sep.isEmpty()) { a.add(s); return a; }
        int start = 0;
        for (;;) {
            int q = s.indexOf(sep, start);
            if (q < 0) { a.add(s.substring(start)); break; }
            a.add(s.substring(start, q));
            start = q + sep.length();
        }
        return a;
    }

    static double timesNum(ArrayList<Double> a, double v) { double c = 0; for (double x : a) if (x == v) c += 1; return c; }
    static double timesStr(ArrayList<String> a, String v) { double c = 0; for (String x : a) if (x.equals(v)) c += 1; return c; }
    static double hasNum(ArrayList<Double> a, double v) { return a.contains(v) ? 1 : 0; }
    static double hasStr(ArrayList<String> a, String v) { return a.contains(v) ? 1 : 0; }

    static String rep(String s, double n) {
        int k = (int) n;
        if (k <= 0) return "";
        return s.repeat(k);
    }
    static double find(String s, String t) {
        int i = s.indexOf(t);
        return i < 0 ? -1 : s.codePointCount(0, i);
    }
    static String sub(String s, double start, double length) {
        int n = (int) len(s);
        int st = Math.min(n, Math.max(0, (int) start));
        int k = Math.min(n - st, Math.max(0, (int) length));
        int from = s.offsetByCodePoints(0, st);
        return s.substring(from, s.offsetByCodePoints(from, k));
    }
    static String repl(String s, String from, String to) {
        if (from.isEmpty()) return s;
        return s.replace(from, to);
    }

    static String now() {
        return java.time.LocalDateTime.now().format(
            java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));
    }
    static String date() { return java.time.LocalDate.now().toString(); }
    static double ts() { return System.currentTimeMillis() / 1000; }

    static String hex(double v) { return Long.toString((long) v, 16); }
    static String bin(double n) { return Long.toString((long) n, 2); }
'''


class JavaGen:
    def __init__(self, ptypes, rtypes, records, class_name):
        self.ptypes = ptypes
        self.rtypes = rtypes
        self.records = records
        self.class_name = class_name
        self.out = []
        self.ind = 2
        self.scopes = [{}]
        self.ret = VOID
        self.tmpn = 0

    def emit(self, text=""):
        self.out.append("    " * self.ind + text)

    def push(self):
        self.scopes.append({})

    def pop(self):
        self.scopes.pop()

    def declare(self, name, t, line):
        for s in reversed(self.scopes):
            if name in s:
                raise KiteError("名字「%s」已经用过了" % name, line)
        self.scopes[-1][name] = (t, java_name(name))

    def lookup(self, name, line):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        raise KiteError("「%s」还没有定义" % name, line)

    def num_lit(self, v):
        if isinstance(v, int):
            return "%d.0" % v
        return repr(float(v))

    def j_string(self, s):
        out = ['"']
        for ch in s:
            if ch == "\\":
                out.append("\\\\")
            elif ch == '"':
                out.append('\\"')
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\t":
                out.append("\\t")
            elif ch == "\r":
                out.append("\\r")
            else:
                out.append(ch)
        out.append('"')
        return "".join(out)

    def java_type(self, t):
        if t in self.records:
            return java_name(t, record=True)
        e = elem_of(t)
        if e in self.records:
            return "ArrayList<%s>" % self.java_type(e)
        return cs(t)

    def to_str(self, code, t):
        if t == STR:
            return code
        if t == NUM:
            return "S(%s)" % code
        if elem_of(t) is not None:
            return "S(%s)" % code
        raise KiteError("这个值不能当文本用")

    def gen_expr(self, n):
        t = type(n)

        if t is Num:
            return (self.num_lit(n.value), NUM)

        if t is Text:
            return (self.j_string(n.value), STR)

        if t is Interp:
            pieces = []
            for p in n.parts:
                code, ty = self.gen_expr(p)
                pieces.append(self.to_str(code, ty))
            acc = pieces[0]
            for p in pieces[1:]:
                acc = "(%s + %s)" % (acc, p)
            return (acc, STR)

        if t is Name:
            ty, cname = self.lookup(n.id, n.line)
            return (cname, ty)

        if t is ListLit:
            return self.gen_list(n)

        if t is Index:
            base, bty = self.gen_expr(n.target)
            idx, ity = self.gen_expr(n.index)
            e = elem_of(bty)
            if e is None:
                raise KiteError("只有数组才能用 [] 取元素", n.line)
            getter = "getNum" if e == NUM else "getList"
            return ("%s(%s, %s, %d)" % (getter, base, idx, n.line), e)

        if t is Slice:
            base, bty = self.gen_expr(n.target)
            f, ft = self.gen_expr(n.from_)
            to, tt = self.gen_expr(n.to)
            if is_matrix(bty):
                raise KiteError("还不能切二维表", n.line)
            if bty == STR:
                return ("sliceStr(%s, %s, %s, %d)" % (base, f, to, n.line), STR)
            if elem_of(bty) is not None:
                return ("sliceList(%s, %s, %s, %d)" % (base, f, to, n.line), bty)
            raise KiteError("切片只能用在文本或一维数组上", n.line)

        if t is Unary:
            code, ty = self.gen_expr(n.operand)
            if n.op == "!":
                return ("B(!((%s) != 0))" % code, NUM)
            return ("(-(%s))" % code, NUM)

        if t is BinOp:
            return self.gen_binop(n)

        if t is Field:
            if n.owner is None:
                return self.gen_call(Call(Name(n.fallback or n.name, n.line), [n.target], n.line))
            base, _ = self.gen_expr(n.target)
            field_type = dict(self.records[n.owner].fields)[n.name]
            return ("(%s).%s" % (base, java_name(n.name)), field_type)

        if t is Call:
            return self.gen_call(n)

        raise KiteError("内部错误：不认识的表达式", getattr(n, "line", 0))

    def gen_list(self, n):
        if not n.items:
            raise KiteError("空数组不支持，至少写一个元素", n.line)
        if isinstance(n.items[0], ListLit):
            rows = []
            cols = None
            elem = None
            for row in n.items:
                if not isinstance(row, ListLit):
                    raise KiteError("二维数组的每一行都要写成 [ ... ]", n.line)
                if cols is None:
                    cols = len(row.items)
                elif len(row.items) != cols:
                    raise KiteError("二维数组每行的长度要一样", n.line)
                codes = []
                for item in row.items:
                    code, ty = self.gen_expr(item)
                    if elem is None:
                        elem = ty
                    elif elem != ty:
                        raise KiteError("二维数组里的元素类型要一致", n.line)
                    codes.append(code)
                rows.append("{" + ", ".join(codes) + "}")
            if elem == NUM:
                return ("arr2(new double[][]{" + ", ".join(rows) + "})",
                        NUM + "[][]")
            return ("arr2s(new String[][]{" + ", ".join(rows) + "})", STR + "[][]")

        codes = []
        elem = None
        for item in n.items:
            code, ty = self.gen_expr(item)
            if elem is None:
                elem = ty
            elif elem != ty:
                raise KiteError("数组里的元素类型要一致（%s 和 %s 混在一起了）"
                                % (type_cn(elem), type_cn(ty)), n.line)
            codes.append(code)
        if elem == NUM:
            return ("arr(%s)" % ", ".join(codes), NUM + "[]")
        if elem in self.records:
            return ("new ArrayList<>(Arrays.asList(%s))" % ", ".join(codes), elem + "[]")
        return ("arrs(%s)" % ", ".join(codes), STR + "[]")

    def gen_binop(self, n):
        op = n.op
        if op == "..":
            raise KiteError("1..5 只能写在 rp 后面", n.line)

        l, lt = self.gen_expr(n.left)
        r, rt = self.gen_expr(n.right)

        if op == "+":
            if lt == STR or rt == STR:
                return ("(%s + %s)" % (self.to_str(l, lt), self.to_str(r, rt)), STR)
            return ("((%s) + (%s))" % (l, r), NUM)

        if op in ("-", "*", "/", "%"):
            return ("((%s) %s (%s))" % (l, op, r), NUM)

        if op in ("==", "!="):
            if lt == STR and rt == STR:
                if op == "==":
                    return ("B((%s).equals(%s))" % (l, r), NUM)
                return ("B(!(%s).equals(%s))" % (l, r), NUM)
            return ("B((%s) %s (%s))" % (l, op, r), NUM)

        if op in ("<", ">", "<=", ">="):
            if lt == STR and rt == STR:
                return ("B((%s).compareTo(%s) %s 0)" % (l, r, op), NUM)
            return ("B(((%s) %s (%s)))" % (l, op, r), NUM)

        if op == "&&":
            return ("B(((%s) != 0) && ((%s) != 0))" % (l, r), NUM)
        if op == "||":
            return ("B(((%s) != 0) || ((%s) != 0))" % (l, r), NUM)

        raise KiteError("不认识的运算符 %s" % op, n.line)

    def gen_call(self, n):
        if not isinstance(n.callee, Name):
            raise KiteError("只能调用有名字的函数", n.line)
        name = n.callee.id

        if name in self.records:
            args = [self.gen_expr(a)[0] for a in n.args]
            return ("new %s(%s)" % (java_name(name, record=True), ", ".join(args)), name)

        if name == "push":
            if len(n.args) != 2:
                raise KiteError("push 要两个参数：数组、要加的值", n.line)
            target = n.args[0]
            if not isinstance(target, Name):
                raise KiteError("push 要作用在变量上，比如 xs.push(3)", n.line)
            ty, cname = self.lookup(target.id, n.line)
            if elem_of(ty) is None:
                raise KiteError("只有数组才能 push", n.line)
            code, ct = self.gen_expr(n.args[1])
            if ct != elem_of(ty):
                raise KiteError("数组元素是%s，不能 push 进去%s"
                                % (type_cn(elem_of(ty)), type_cn(ct)), n.line)
            return ("%s.add(%s)" % (cname, code), VOID)

        if name in ("serve", "form", "html"):
            raise KiteError("Java 版还不支持 %s" % name, n.line)

        raw = [self.gen_expr(a) for a in n.args]
        args = [c for c, _ in raw]

        if name == "num":
            return ("num(%s, %d)" % (args[0], n.line), NUM)
        if name == "ask":
            return ("ask(%s)" % (args[0] if args else '""'), STR)

        simple = {
            "txt": STR, "up": STR, "low": STR,
            "trim": STR, "read": STR, "exist": NUM,
            "now": STR, "date": STR, "ts": NUM, "hex": STR, "bin": STR,
        }
        if name in simple:
            return ("%s(%s)" % (name, ", ".join(args)), simple[name])

        if name == "len":
            if raw[0][1] == STR:
                return ("len(%s)" % args[0], NUM)
            return ("lenList(%s)" % args[0], NUM)

        if name in ("sum", "avg", "max", "min"):
            return ("%s(%s)" % (name, ", ".join(args)), NUM)

        if name in ("times", "has"):
            fn = name + ("Num" if elem_of(raw[0][1]) == NUM else "Str")
            return ("%s(%s, %s)" % (fn, args[0], args[1]), NUM)

        if name == "sort":
            fn = "sortNum" if elem_of(raw[0][1]) == NUM else "sortStr"
            return ("%s(%s)" % (fn, args[0]), VOID)

        if name == "join":
            fn = "joinNum" if elem_of(raw[0][1]) == NUM else "joinStr"
            sep = args[1] if len(args) > 1 else '","'
            return ("%s(%s, %s)" % (fn, args[0], sep), STR)
        if name == "split":
            return ("split(%s, %s)" % (args[0], args[1] if len(args) > 1 else '","'), STR + "[]")
        if name in ("rep", "repl"):
            return ("%s(%s)" % (name, ", ".join(args)), STR)
        if name == "find":
            return ("find(%s, %s)" % (args[0], args[1]), NUM)
        if name == "sub":
            return ("sub(%s, %s, %s)" % (args[0], args[1], args[2]), STR)
        if name == "rand":
            return ("rand(%s)" % args[0], NUM)
        if name == "seed":
            return ("seed(%s)" % args[0], VOID)
        if name == "write" or name == "del":
            return ("%s(%s)" % (name, ", ".join(args)), VOID)
        if name == "mat":
            return ("mat(%s, %s, %s, %d)" % (args[0], args[1], args[2], n.line),
                    (NUM if raw[2][1] == NUM else STR) + "[][]")
        if name == "abs":
            return ("Math.abs(%s)" % args[0], NUM)
        if name == "floor":
            return ("Math.floor(%s)" % args[0], NUM)
        if name == "round":
            return ("Math.floor((%s) + 0.5)" % args[0], NUM)
        if name == "sqrt":
            return ("Math.sqrt(%s)" % args[0], NUM)
        if name == "pow":
            return ("Math.pow(%s, %s)" % (args[0], args[1]), NUM)

        if name in self.rtypes:
            params = self.ptypes[name]
            if len(args) != len(params):
                raise KiteError("%s 需要 %d 个参数，给了 %d 个"
                                % (name, len(params), len(args)), n.line)
            return ("%s(%s)" % (java_name(name, function=True), ", ".join(args)),
                    self.rtypes[name])

        raise KiteError("没有叫「%s」的函数" % name, n.line)

    # ---------- 语句 ----------

    def gen_block(self, block):
        self.push()
        self.ind += 1
        for stmt in block.stmts:
            self.gen_stmt(stmt)
        self.ind -= 1
        self.pop()

    def gen_stmt(self, node):
        t = type(node)

        if t is ExprStmt:
            code, ty = self.gen_expr(node.expr)
            if isinstance(node.expr, Field) and node.expr.owner is not None:
                self.emit("%s %s = %s;" % (self.java_type(ty), self.new_tmp(), code))
            else:
                self.emit(code + ";")
            return

        if t is Assign:
            self.gen_assign(node)
            return

        if t is Say:
            parts = []
            for e in node.exprs:
                code, ty = self.gen_expr(e)
                parts.append(self.to_str(code, ty))
            self.emit("out.println(%s);" % " + \" \" + ".join(parts))
            return

        if t is If:
            first = True
            for cond, body in node.branches:
                code, cty = self.gen_expr(cond)
                kw = "if" if first else "else if"
                self.emit("%s ((%s) != 0)" % (kw, code))
                self.emit("{")
                self.gen_block(body)
                self.emit("}")
                first = False
            if node.orelse is not None:
                self.emit("else")
                self.emit("{")
                self.gen_block(node.orelse)
                self.emit("}")
            return

        if t is Loop:
            self.gen_loop(node)
            return

        if t is Return:
            if node.expr is None:
                self.emit("return;")
                return
            code, ty = self.gen_expr(node.expr)
            self.emit("return %s;" % code)
            return

        if t is Break:
            self.emit("break;")
            return

        if t is Continue:
            self.emit("continue;")
            return

        if t in (FnDef, RecordDef):
            return

        raise KiteError("内部错误：不认识的语句", getattr(node, "line", 0))

    def gen_assign(self, node):
        code, ty = self.gen_expr(node.value)

        if isinstance(node.target, Index):
            base, bty = self.gen_expr(node.target.target)
            idx, ity = self.gen_expr(node.target.index)
            e = elem_of(bty)
            if e is None:
                raise KiteError("只有数组才能按下标赋值", node.line)
            if elem_of(e) is not None:
                raise KiteError("不能整行赋值，用 m[i][j] = ... 一个个改", node.line)
            setter = "setNum" if e == NUM else "setList"
            self.emit("%s(%s, %s, %s, %d);" % (setter, base, idx, code, node.line))
            return

        name = node.target.id
        found = None
        for s in reversed(self.scopes):
            if name in s:
                found = s[name]
                break
        if found is None:
            self.declare(name, ty, node.line)
            self.emit("%s %s = %s; /* kite:%d */"
                      % (self.java_type(ty), java_name(name), code, node.line))
        else:
            self.emit("%s = %s;" % (found[1], code))

    def new_tmp(self):
        self.tmpn += 1
        return "kite_tmp_%d" % self.tmpn

    def gen_loop(self, node):
        if node.mode == "until":
            code, _ = self.gen_expr(node.source)
            self.emit("while (!((%s) != 0))" % code)
            self.emit("{")
            self.gen_block(node.body)
            self.emit("}")
            return

        # The counter can shadow another Kite name, including an outer counter.
        key = node.name or "count"
        name = self.new_tmp()
        src = node.source
        self.emit("{")
        self.ind += 1
        item_source = None
        if isinstance(src, BinOp) and src.op == "..":
            a, _ = self.gen_expr(src.left)
            b, _ = self.gen_expr(src.right)
            first, last, descending = self.new_tmp(), self.new_tmp(), self.new_tmp()
            self.emit("double %s = %s;" % (first, a))
            self.emit("double %s = %s;" % (last, b))
            self.emit("boolean %s = %s > %s;" % (descending, first, last))
            header = ("for (double %s = %s; Double.isFinite(%s) && Double.isFinite(%s) && "
                      "(%s ? %s >= %s : %s <= %s); %s = nextCount(%s, %s ? -1 : 1))"
                      % (name, first, first, last, descending, name, last, name, last, name, name, descending))
            ty = NUM
        else:
            code, ty = self.gen_expr(src)
            item = elem_of(ty)
            if item is not None:
                arr, index = self.new_tmp(), self.new_tmp()
                self.emit("%s %s = %s;" % (self.java_type(ty), arr, code))
                header = "for (int %s = 0; %s < %s.size(); %s++)" % (index, index, arr, index)
                item_source = "%s.get(%s)" % (arr, index)
                ty = item
            else:
                limit = self.new_tmp()
                self.emit("double %s = %s;" % (limit, code))
                header = ("for (double %s = 1; Double.isFinite(%s) && %s <= %s; %s = nextCount(%s, 1))"
                          % (name, limit, name, limit, name, name))
        self.emit(header)
        self.emit("{")
        self.push()
        self.scopes[-1][key] = (ty, name)
        self.ind += 1
        if item_source is not None:
            self.emit("%s %s = %s;" % (self.java_type(ty), name, item_source))
        for stmt in node.body.stmts:
            self.gen_stmt(stmt)
        self.ind -= 1
        self.pop()
        self.emit("}")
        self.ind -= 1
        self.emit("}")

    # ---------- 文件 ----------

    def gen_record(self, record):
        name = java_name(record.name, record=True)
        fields = [(self.java_type(ty), java_name(field)) for field, ty in record.fields]
        lines = ["    static final class %s" % name, "    {"]
        for ty, field in fields:
            lines.append("        final %s %s;" % (ty, field))
        params = ", ".join("%s %s" % (ty, field) for ty, field in fields)
        lines.append("        %s(%s)" % (name, params))
        lines.append("        {")
        for _, field in fields:
            lines.append("            this.%s = %s;" % (field, field))
        lines.extend(["        }", "    }", ""])
        return lines

    def gen_function(self, fn):
        self.scopes = [{}]
        self.ind = 2
        self.ret = self.rtypes[fn.name]
        for (pname, _), ty in zip(fn.params, self.ptypes[fn.name]):
            self.scopes[-1][pname] = (ty, java_name(pname))
        for stmt in fn.body.stmts:
            self.gen_stmt(stmt)
        params = ", ".join("%s %s" % (self.java_type(t), java_name(pn))
                           for (pn, _), t in zip(fn.params, self.ptypes[fn.name]))
        head = "static %s %s(%s)" % (self.java_type(self.rtypes[fn.name]),
                                     java_name(fn.name, function=True), params)
        return head, self.out

    def build(self, program):
        funcs = [s for s in program.stmts if isinstance(s, FnDef)]
        top = [s for s in program.stmts if not isinstance(s, (FnDef, RecordDef))]

        lines = ["// 由 kite 自动生成。改代码请改 .kite 源文件。",
                 "import java.util.*;",
                 "",
                 "public class %s" % self.class_name,
                 "{"]

        for record in self.records.values():
            lines.extend(self.gen_record(record))

        for fn in funcs:
            self.out = []
            head, body = self.gen_function(fn)
            lines.append("    " + head)
            lines.append("    {")
            lines.extend(body)
            lines.append("    }")
            lines.append("")

        self.out = []
        self.scopes = [{}]
        self.ind = 2
        for stmt in top:
            self.gen_stmt(stmt)
        lines.append("    static void mainBody()")
        lines.append("    {")
        lines.extend(self.out)
        lines.append("    }")
        lines.append("")
        lines.append("    public static void main(String[] args)")
        lines.append("    {")
        lines.append("        try")
        lines.append("        {")
        lines.append("            mainBody();")
        lines.append("        }")
        lines.append("        catch (RuntimeException e)")
        lines.append("        {")
        lines.append('            err.println("出错了：" + e.getMessage());')
        lines.append("            System.exit(1);")
        lines.append("        }")
        lines.append("    }")

        lines.append(PRELUDE)
        lines.append("}")
        return "\n".join(lines)


def class_name_for(path):
    base = os.path.splitext(os.path.basename(path))[0]
    parts = [p for p in base.replace("-", "_").split("_") if p]
    name = "".join(p[:1].upper() + p[1:] for p in parts) or "Kite"
    name = "".join(ch for ch in name if ch.isalnum())
    if not name or not name[0].isalpha():
        name = "Kite" + name
    return name


def output_path(src_path):
    return os.path.join(os.path.dirname(os.path.abspath(src_path)),
                        class_name_for(src_path) + ".java")


def generate(src, path):
    program = load_program(src, path)
    require_backend(program, "Java")
    typer = Typer(program)
    ptypes, rtypes = typer.run()
    return JavaGen(ptypes, rtypes, typer.records, class_name_for(path)).build(program)


def main(argv):
    if len(argv) < 2:
        print("用法：python3 kite_java.py 程序.kite")
        return 2
    path = argv[1]
    try:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
    except OSError as e:
        print("读不了：" + str(e))
        return 1
    try:
        code = generate(src, path)
    except KiteError as e:
        print("出错了：%s" % e.msg, file=sys.stderr)
        if e.line:
            print("  第 %d 行" % e.line, file=sys.stderr)
        return 1
    out = output_path(path)
    with open(out, "w", encoding="utf-8") as f:
        f.write(code)
    print("已生成 " + out, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
