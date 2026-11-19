#!/usr/bin/env python3
"""
kite → JavaScript。

    python3 kite.py 程序.kite --js

生成的 .js 既能 node 跑，也能丢进浏览器 <script>。
"""

import os
import sys

from kite import (
    load_program, require_backend, Typer, KiteError,
    Num, Text, Interp, Name, ListLit, BinOp, Unary, Call, Field, Index, Slice,
    Assign, Say, If, Loop, FnDef, RecordDef, Return, Break, Continue, ExprStmt,
    NUM, STR, VOID, elem_of, is_matrix, type_cn,
)

def js_name(name, function=False, record=False):
    prefix = "kite_record" if record else "kite_fn" if function else "kite_var"
    if name.isascii() and name.isidentifier():
        return prefix + "_" + name
    return prefix + "u_" + name.encode("utf-8").hex()


PRELUDE = r'''"use strict";

// ---------------- kite 运行时 ----------------

function RT_fail(msg, line) {
    throw new Error("第 " + line + " 行：" + msg);
}

function RT_index(i, n, line) {
    if (!Number.isFinite(i)) RT_fail("下标要是有限数字", line);
    let k = Math.trunc(i);
    if (k === 0) RT_fail("下标从 1 开始数，没有第 0 个", line);
    if (k < 0) k = n + k + 1;
    if (k < 1 || k > n) {
        RT_fail("越界（下标 " + i + "，长度 " + n + "，从 1 开始数）", line);
    }
    return k - 1;
}

function RT_get(a, i, line) {
    return a[RT_index(i, a.length, line)];
}

function RT_set(a, i, v, line) {
    a[RT_index(i, a.length, line)] = v;
}

function RT_slice(a, f, t, line) {
    if (!Number.isFinite(f) || !Number.isFinite(t)) RT_fail("切片下标要是有限数字", line);
    const text = typeof a === "string";
    if (text) a = Array.from(a);
    const n = a.length;
    let from = Math.trunc(f);
    let to = Math.trunc(t);
    if (from < 0) from = n + from + 1;
    if (to < 0) to = n + to + 1;
    if (from < 1) from = 1;
    if (to > n) to = n;
    const part = from > to ? [] : a.slice(from - 1, to);
    return text ? part.join("") : part;
}

function RT_push(a, v) {
    a.push(v);
}

const RT_float = new DataView(new ArrayBuffer(8));

function RT_num_text(x) {
    if (!Number.isFinite(x)) return Number.isNaN(x) ? "nan" : x < 0 ? "-inf" : "inf";
    if (Number.isInteger(x) && Math.abs(x) < 1e15) return String(x);
    const sign = x < 0 ? "-" : "";
    // Build the exact decimal digits of the binary double, then round half to even.
    RT_float.setFloat64(0, Math.abs(x));
    const bits = RT_float.getBigUint64(0);
    const field = Number(bits >> 52n);
    const m = (bits & ((1n << 52n) - 1n)) | (field ? 1n << 52n : 0n);
    const power = (field || 1) - 1075;
    const digits = (power >= 0 ? m << BigInt(power) : m * 5n ** BigInt(-power)).toString();
    let e = digits.length - 1 + Math.min(0, power);
    let rounded = digits.slice(0, 15);
    const next = digits[15];
    if (next > "5" || (next === "5" && (/[1-9]/.test(digits.slice(16)) || Number(rounded[14]) % 2))) {
        rounded = String(Number(rounded) + 1);
        if (rounded.length > 15) e++;
    }
    rounded = rounded.replace(/0+$/, "");
    if (e < -4 || e >= 15) {
        return sign + rounded[0] + (rounded.length > 1 ? "." + rounded.slice(1) : "") + "e" + e;
    }
    if (e < 0) return sign + "0." + "0".repeat(-e - 1) + rounded;
    if (rounded.length <= e + 1) return sign + rounded.padEnd(e + 1, "0");
    return sign + rounded.slice(0, e + 1) + "." + rounded.slice(e + 1);
}

function RT_show(x) {
    if (Array.isArray(x)) return "[" + x.map(RT_show).join(", ") + "]";
    if (typeof x === "string") return JSON.stringify(x);
    return RT_num_text(x);
}

function RT_next_count(x, step) {
    const next = x + step;
    return next === x ? NaN : next;
}

const RT_MASK = (1n << 64n) - 1n;
let RT_rng = 0n;

function seed(s) {
    RT_rng = (BigInt(Math.trunc(s)) * 6364136223846793005n
              + 1442695040888963407n) & RT_MASK;
    if (RT_rng === 0n) RT_rng = 88172645463325252n;
}

function RT_next() {
    let x = RT_rng;
    x = (x ^ (x << 13n)) & RT_MASK;
    x = (x ^ (x >> 7n)) & RT_MASK;
    x = (x ^ (x << 17n)) & RT_MASK;
    RT_rng = x;
    return x;
}

function rand(n) {
    if (RT_rng === 0n) { seed(Math.floor(Date.now() / 1000)); RT_next(); }
    const m = BigInt(Math.trunc(n));
    if (m <= 0n) return 0;
    return Number(RT_next() % m);
}

const RT_node = (typeof process !== "undefined" && process.versions
                 && process.versions.node);

function RT_require(mod) {
    if (!RT_node) RT_fail("这个功能只能在 Node 里用（浏览器没有文件）", 0);
    return require(mod);
}

let RT_input = null;
let RT_input_at = 0, RT_input_end = 0;
let RT_skip_lf = false;

function ask(prompt) {
    if (!RT_node) RT_fail("ask 只能在 Node 里用（浏览器没有标准输入）", 0);
    if (prompt) process.stdout.write(prompt);
    const fs = RT_require("fs");
    if (RT_input === null) RT_input = Buffer.alloc(4096);
    const bytes = [];
    while (true) {
        if (RT_input_at === RT_input_end) {
            try { RT_input_end = fs.readSync(0, RT_input, 0, RT_input.length, null); }
            catch (e) {
                if (e.code === "EINTR") continue;
                RT_fail("读不了标准输入：" + e.message, 0);
            }
            RT_input_at = 0;
            if (RT_input_end === 0) break;
        }
        const b = RT_input[RT_input_at++];
        if (RT_skip_lf) {
            RT_skip_lf = false;
            if (b === 10) continue;
        }
        if (b === 13 || b === 10) {
            RT_skip_lf = b === 13;
            break;
        }
        bytes.push(b);
    }
    return Buffer.from(bytes).toString("utf8");
}

function read(path) {
    try { return RT_require("fs").readFileSync(path, "utf8"); }
    catch (e) { return ""; }
}

function write(path, s) {
    RT_require("fs").writeFileSync(path, s);
}

function exist(path) {
    try { RT_require("fs").accessSync(path); return 1; }
    catch (e) { return 0; }
}

function del(path) {
    try { RT_require("fs").unlinkSync(path); } catch (e) {}
}

// ---------------- 内置函数 ----------------

function len(x) { return typeof x === "string" ? Array.from(x).length : x.length; }

function txt(x) { return typeof x === "string" ? x : RT_show(x); }

function num(s, line) {
    s = s.replace(/^[\t\n\v\f\r ]+|[\t\n\v\f\r ]+(?![\s\S])/g, "");
    if (s === "") return 0;
    if (/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?(?![\s\S])/.test(s)) {
        const value = Number(s);
        if (Number.isFinite(value)) return value;
    }
    RT_fail("不能转成数字", line);
}
function up(s) { return s.toUpperCase(); }
function low(s) { return s.toLowerCase(); }
function trim(s) { return s.trim(); }

function sum(a) { let s = 0; for (const v of a) s += v; return s; }
function avg(a) { return a.length ? sum(a) / a.length : 0; }
function max(a) { let m = a.length ? a[0] : 0; for (const v of a) if (v > m) m = v; return m; }
function min(a) { let m = a.length ? a[0] : 0; for (const v of a) if (v < m) m = v; return m; }

function sort(a) {
    if (a.length && typeof a[0] === "number") a.sort((x, y) => x - y);
    else a.sort();
    return a;
}

function join(a, sep = ",") { return a.map(txt).join(sep); }
function split(s, sep = ",") { return sep === "" ? [s] : s.split(sep); }

function times(a, v) {
    let c = 0;
    for (const x of a) if (x === v) c += 1;
    return c;
}

function has(a, v) { return a.includes(v) ? 1 : 0; }

function rep(s, n) {
    let k = Math.trunc(n);
    if (k <= 0) return "";
    return s.repeat(k);
}

function find(s, t) {
    const i = s.indexOf(t);
    return i < 0 ? -1 : Array.from(s.slice(0, i)).length;
}
function sub(s, start, len) {
    const chars = Array.from(s);
    const at = Math.min(chars.length, Math.max(0, Math.trunc(start) || 0));
    const count = Math.max(0, Math.trunc(len) || 0);
    return chars.slice(at, at + count).join("");
}
function repl(s, from, to) {
    if (from === "") return s;
    return s.split(from).join(to);
}

function now() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate())
        + " " + p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
}
function date() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
}
function ts() { return Math.floor(Date.now() / 1000); }

function hex(n) { return Math.trunc(n).toString(16); }
function bin(n) { return Math.trunc(n).toString(2); }

function mat(rows, cols, fill, line) {
    const r = Math.trunc(rows), c = Math.trunc(cols);
    if (!Number.isFinite(r) || !Number.isFinite(c) || r < 1 || c < 1 || r * c > 10000000) {
        RT_fail("mat 的尺寸不合理", line);
    }
    const a = [];
    for (let i = 0; i < r; i++) {
        const row = [];
        for (let j = 0; j < c; j++) row.push(fill);
        a.push(row);
    }
    return a;
}
'''

BIN_OPS = {"+": "+", "-": "-", "*": "*", "/": "/", "%": "%"}
CMP_OPS = {"==": "===", "!=": "!==", "<": "<", ">": ">", "<=": "<=", ">=": ">="}


class JsGen:
    def __init__(self, ptypes, rtypes, records):
        self.ptypes = ptypes
        self.rtypes = rtypes
        self.records = records
        self.out = []
        self.ind = 1
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
        self.scopes[-1][name] = (t, js_name(name))

    def lookup(self, name, line):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        raise KiteError("「%s」还没有定义" % name, line)

    # ---------- 表达式 ----------

    def num_lit(self, v):
        if isinstance(v, int):
            return str(v)
        return repr(float(v))

    def js_string(self, s):
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

    def to_str(self, code, t):
        if t == STR:
            return code
        if t == NUM:
            return "RT_num_text(%s)" % code
        if elem_of(t) is not None:
            return "RT_show(%s)" % code
        raise KiteError("这个值不能当文本用")

    def gen_expr(self, n):
        t = type(n)

        if t is Num:
            return (self.num_lit(n.value), NUM)

        if t is Text:
            return (self.js_string(n.value), STR)

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
            return ("RT_get(%s, %s, %d)" % (base, idx, n.line), e)

        if t is Slice:
            base, bty = self.gen_expr(n.target)
            f, ft = self.gen_expr(n.from_)
            to, tt = self.gen_expr(n.to)
            if bty == STR:
                return ("RT_slice(%s, %s, %s, %d)" % (base, f, to, n.line), STR)
            if is_matrix(bty):
                raise KiteError("还不能切二维表", n.line)
            e = elem_of(bty)
            if e is None:
                raise KiteError("切片只能用在文本或一维数组上", n.line)
            return ("RT_slice(%s, %s, %s, %d)" % (base, f, to, n.line), bty)

        if t is Unary:
            code, ty = self.gen_expr(n.operand)
            if n.op == "!":
                return ("((%s) ? 0 : 1)" % code, NUM)
            return ("(-(%s))" % code, NUM)

        if t is BinOp:
            return self.gen_binop(n)

        if t is Field:
            if n.owner is None:
                return self.gen_call(Call(Name(n.fallback or n.name, n.line), [n.target], n.line))
            base, _ = self.gen_expr(n.target)
            field_type = dict(self.records[n.owner].fields)[n.name]
            return ("(%s).%s" % (base, js_name(n.name)), field_type)

        if t is Call:
            return self.gen_call(n)

        raise KiteError("内部错误：不认识的表达式", getattr(n, "line", 0))

    def gen_list(self, n):
        if not n.items:
            raise KiteError("空数组不支持，至少写一个元素", n.line)
        if isinstance(n.items[0], ListLit):
            rows = [self.gen_list(row)[0] for row in n.items if isinstance(row, ListLit)]
            if len(rows) != len(n.items):
                raise KiteError("二维数组的每一行都要写成 [ ... ]", n.line)
            cols = len(n.items[0].items)
            for row in n.items:
                if len(row.items) != cols:
                    raise KiteError("二维数组每行的长度要一样", n.line)
            _, row_type = self.gen_list(n.items[0])
            return ("[" + ", ".join(rows) + "]", row_type + "[]")
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
        return ("[" + ", ".join(codes) + "]", elem + "[]")

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

        if op in BIN_OPS:
            return ("((%s) %s (%s))" % (l, BIN_OPS[op], r), NUM)

        if op in CMP_OPS:
            if lt == STR and rt == STR:
                return ("((%s) %s (%s) ? 1 : 0)" % (l, CMP_OPS[op], r), NUM)
            return ("((%s) %s (%s) ? 1 : 0)" % (l, CMP_OPS[op], r), NUM)

        if op == "&&":
            return ("((( %s ) !== 0 && ( %s ) !== 0) ? 1 : 0)" % (l, r), NUM)
        if op == "||":
            return ("((( %s ) !== 0 || ( %s ) !== 0) ? 1 : 0)" % (l, r), NUM)

        raise KiteError("不认识的运算符 %s" % op, n.line)

    def gen_call(self, n):
        if not isinstance(n.callee, Name):
            raise KiteError("只能调用有名字的函数", n.line)
        name = n.callee.id

        if name in self.records:
            args = [self.gen_expr(a)[0] for a in n.args]
            return ("%s(%s)" % (js_name(name, record=True), ", ".join(args)), name)

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
            return ("RT_push(%s, %s)" % (cname, code), VOID)

        if name in ("serve", "form", "html"):
            raise KiteError("JS 版还不支持 %s（网页界面请用 C 后端）" % name, n.line)

        raw = [self.gen_expr(a) for a in n.args]
        args = [c for c, _ in raw]

        two_arg_default = name in ("join", "split") and len(args) == 1
        if two_arg_default:
            args = args + ['","']

        if name in ("sum", "avg", "max", "min"):
            return ("%s(%s)" % (name, args[0]), NUM)
        if name == "sort":
            return ("sort(%s)" % args[0], VOID)
        if name == "join":
            return ("join(%s, %s)" % (args[0], args[1]), STR)
        if name == "split":
            return ("split(%s, %s)" % (args[0], args[1]), STR + "[]")
        if name in ("times", "has"):
            return ("%s(%s, %s)" % (name, args[0], args[1]), NUM)
        if name in ("len", "txt", "num", "up", "low", "trim", "ask", "read",
                    "rand", "abs", "floor", "round", "sqrt", "pow", "rep",
                    "find", "sub", "repl", "hex", "bin", "mat"):
            if name in ("abs", "floor", "round", "sqrt"):
                return ("Math.%s(%s)" % (name, args[0]), NUM)
            if name == "pow":
                return ("Math.pow(%s, %s)" % (args[0], args[1]), NUM)
            if name == "mat":
                return ("mat(%s, %s, %s, %d)" % (args[0], args[1], args[2], n.line),
                        (NUM if raw[2][1] == NUM else STR) + "[][]")
            if name == "rand":
                return ("rand(%s)" % args[0], NUM)
            if name == "rep":
                return ("rep(%s, %s)" % (args[0], args[1]), STR)
            if name == "find":
                return ("find(%s, %s)" % (args[0], args[1]), NUM)
            if name == "sub":
                return ("sub(%s, %s, %s)" % (args[0], args[1], args[2]), STR)
            if name == "repl":
                return ("repl(%s, %s, %s)" % (args[0], args[1], args[2]), STR)
            if name == "hex":
                return ("hex(%s)" % args[0], STR)
            if name == "bin":
                return ("bin(%s)" % args[0], STR)
            if name == "len":
                return ("len(%s)" % args[0], NUM)
            if name == "num":
                return ("num(%s, %d)" % (args[0], n.line), NUM)
            if name == "txt":
                return ("txt(%s)" % args[0], STR)
            return ("%s(%s)" % (name, ", ".join(args)), STR)
        if name in ("seed", "write", "del"):
            return ("%s(%s)" % (name, ", ".join(args)), VOID)
        if name in ("now", "date", "ts", "exist"):
            if name in ("now", "date"):
                return ("%s()" % name, STR)
            if name == "ts":
                return ("ts()", NUM)
            return ("exist(%s)" % args[0], NUM)

        if name in self.rtypes:
            params = self.ptypes[name]
            if len(args) != len(params):
                raise KiteError("%s 需要 %d 个参数，给了 %d 个"
                                % (name, len(params), len(args)), n.line)
            return ("%s(%s)" % (js_name(name, function=True), ", ".join(args)),
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
            self.emit(code + ";")
            return

        if t is Assign:
            self.gen_assign(node)
            return

        if t is Say:
            parts = []
            for e in node.exprs:
                code, ty = self.gen_expr(e)
                if elem_of(ty) is not None:
                    parts.append("RT_show(%s)" % code)
                else:
                    parts.append(self.to_str(code, ty))
            self.emit("console.log(%s);" % ", ".join(parts))
            return

        if t is If:
            first = True
            for cond, body in node.branches:
                code, cty = self.gen_expr(cond)
                kw = "if" if first else "else if"
                self.emit("%s ((%s) !== 0)" % (kw, code))
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
            self.emit("RT_set(%s, %s, %s, %d);"
                      % (base, idx, code, node.line))
            return

        name = node.target.id
        found = None
        for s in reversed(self.scopes):
            if name in s:
                found = s[name]
                break
        if found is None:
            self.declare(name, ty, node.line)
            self.emit("let %s = %s; /* kite:%d */" % (js_name(name), code, node.line))
        else:
            self.emit("%s = %s;" % (found[1], code))

    def new_tmp(self):
        self.tmpn += 1
        return "kite_tmp_%d" % self.tmpn

    def gen_loop(self, node):
        if node.mode == "until":
            code, _ = self.gen_expr(node.source)
            self.emit("while (!((%s) !== 0))" % code)
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
        if isinstance(src, BinOp) and src.op == "..":
            a, _ = self.gen_expr(src.left)
            b, _ = self.gen_expr(src.right)
            first, last, descending = self.new_tmp(), self.new_tmp(), self.new_tmp()
            self.emit("const %s = %s;" % (first, a))
            self.emit("const %s = %s;" % (last, b))
            self.emit("const %s = %s > %s;" % (descending, first, last))
            header = ("for (let %s = %s; Number.isFinite(%s) && Number.isFinite(%s) && "
                      "(%s ? %s >= %s : %s <= %s); %s = RT_next_count(%s, %s ? -1 : 1))"
                      % (name, first, first, last, descending, name, last, name, last, name, name, descending))
            ty = NUM
        else:
            code, ty = self.gen_expr(src)
            item = elem_of(ty)
            if item is not None:
                header = "for (let %s of (%s))" % (name, code)
                ty = item
            else:
                limit = self.new_tmp()
                self.emit("const %s = %s;" % (limit, code))
                header = ("for (let %s = 1; Number.isFinite(%s) && %s <= %s; %s = RT_next_count(%s, 1))"
                          % (name, limit, name, limit, name, name))
        self.emit(header)
        self.emit("{")
        self.push()
        self.scopes[-1][key] = (ty, name)
        self.ind += 1
        for stmt in node.body.stmts:
            self.gen_stmt(stmt)
        self.ind -= 1
        self.pop()
        self.emit("}")
        self.ind -= 1
        self.emit("}")

    # ---------- 文件 ----------

    def gen_record(self, record):
        name = js_name(record.name, record=True)
        fields = [js_name(field) for field, _ in record.fields]
        return ["function %s(%s)" % (name, ", ".join(fields)),
                "{", "    return Object.freeze({%s});" % ", ".join(fields), "}", ""]

    def gen_function(self, fn):
        self.scopes = [{}]
        self.ind = 1
        self.ret = self.rtypes[fn.name]
        for (pname, _), ty in zip(fn.params, self.ptypes[fn.name]):
            self.scopes[-1][pname] = (ty, js_name(pname))
        for stmt in fn.body.stmts:
            self.gen_stmt(stmt)
        params = ", ".join(js_name(pn) for pn, _ in fn.params)
        return "function %s(%s)" % (js_name(fn.name, function=True), params), self.out

    def build(self, program):
        lines = ["// 由 kite 自动生成。改代码请改 .kite 源文件。", PRELUDE]

        funcs = [s for s in program.stmts if isinstance(s, FnDef)]
        top = [s for s in program.stmts if not isinstance(s, (FnDef, RecordDef))]

        for record in self.records.values():
            lines.extend(self.gen_record(record))

        for fn in funcs:
            self.out = []
            head, body = self.gen_function(fn)
            lines.append(head)
            lines.append("{")
            lines.extend(body)
            lines.append("}")
            lines.append("")

        self.out = []
        self.scopes = [{}]
        self.ind = 1
        for stmt in top:
            self.gen_stmt(stmt)
        lines.append("function main()")
        lines.append("{")
        lines.extend("    " + l[4:] if l.startswith("    ") else l for l in self.out)
        lines.append("}")
        lines.append("")
        lines.append("try { main(); }")
        lines.append("catch (e) {")
        lines.append('    if (typeof console !== "undefined") console.error("出错了：" + e.message);')
        lines.append('    if (typeof process !== "undefined") process.exit(1);')
        lines.append("}")
        return "\n".join(lines)


def output_path(src_path):
    return os.path.splitext(src_path)[0] + ".js"


def generate(src, path):
    program = load_program(src, path)
    require_backend(program, "JavaScript")
    typer = Typer(program)
    ptypes, rtypes = typer.run()
    return JsGen(ptypes, rtypes, typer.records).build(program)


def main(argv):
    if len(argv) < 2:
        print("用法：python3 kite_js.py 程序.kite")
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
