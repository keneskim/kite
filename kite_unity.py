#!/usr/bin/env python3
"""
kite → Unity C# 脚本。

    python3 kite.py 游戏.kite --unity

生成 游戏.cs（类名和文件名一致，Unity 要求）。
把生成的 .cs 丢进 Assets，挂到一个方块上就能跑。
"""

import os
import sys

from kite import (
    load_program, require_backend, Typer, KiteError,
    Num, Text, Interp, Name, ListLit, BinOp, Unary, Call, Field, Index, Slice,
    Block, Assign, Say, If, Loop, FnDef, RecordDef, Return, Break, Continue, ExprStmt,
    NUM, STR, VOID, elem_of, type_cn,
)

# Unity 版能用的内置函数：名字 -> 返回类型
UNITY_TYPES = {
    "key": NUM, "on_ground": NUM, "move_x": VOID, "jump": VOID,
    "x": NUM, "y": NUM, "set_pos": VOID,
    "txt": STR, "num": NUM, "len": NUM, "up": STR, "low": STR, "trim": STR,
}

SIMPLE_BUILTINS = {
    "txt": lambda args: "S(%s)" % args[0],
    "up": lambda args: "(%s).ToUpper()" % args[0],
    "low": lambda args: "(%s).ToLower()" % args[0],
    "trim": lambda args: "(%s).Trim()" % args[0],
    "x": lambda args: "X()",
    "y": lambda args: "Y()",
    "on_ground": lambda args: "OnGround()",
    "key": lambda args: "Key(%s)" % args[0],
    "move_x": lambda args: "MoveX(%s)" % args[0],
    "jump": lambda args: "Jump(%s)" % args[0],
    "set_pos": lambda args: "SetPos(%s, %s)" % (args[0], args[1]),
}

ARITY = {"key": 1, "on_ground": 0, "move_x": 1, "jump": 1, "x": 0, "y": 0,
         "set_pos": 2, "txt": 1, "num": 1, "len": 1, "up": 1, "low": 1, "trim": 1}


def unity_name(name, function=False, record=False):
    prefix = "kite_record" if record else "kite_fn" if function else "kite_var"
    if name.isascii() and name.isidentifier():
        return prefix + "_" + name
    return prefix + "u_" + name.encode("utf-8").hex()


class UnityGen:
    def __init__(self, ptypes, rtypes, records, class_name):
        self.ptypes = ptypes
        self.rtypes = rtypes
        self.records = records
        self.class_name = class_name
        self.out = []
        self.ind = 1
        self.scopes = [{}]
        self.ret = VOID
        self.tmpn = 0

    # ---------- 小工具 ----------

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
        self.scopes[-1][name] = (t, unity_name(name))

    def lookup(self, name, line):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        raise KiteError("「%s」还没有定义" % name, line)

    def cs_type(self, t):
        if t == VOID:
            return "void"
        if t == NUM:
            return "double"
        if t == STR:
            return "string"
        if t in self.records:
            return unity_name(t, record=True)
        e = elem_of(t)
        if e in self.records:
            return "List<%s>" % self.cs_type(e)
        raise KiteError("Unity 版还不支持%s" % type_cn(t))

    # ---------- 表达式 ----------

    def num_lit(self, v):
        if isinstance(v, int):
            return "%d.0" % v
        return repr(float(v))

    def cs_string(self, s):
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
            else:
                out.append(ch)
        out.append('"')
        return "".join(out)

    def to_str(self, code, t):
        if t == STR:
            return code
        if t == NUM:
            return "S(%s)" % code
        raise KiteError("这个值不能当文本用")

    def gen_expr(self, n):
        t = type(n)

        if t is Num:
            return (self.num_lit(n.value), NUM)

        if t is Text:
            return (self.cs_string(n.value), STR)

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
            if not n.items:
                raise KiteError("空数组不支持，至少写一个元素", n.line)
            first, elem = self.gen_expr(n.items[0])
            if elem not in self.records:
                raise KiteError("Unity 版只支持记录数组", n.line)
            codes = [first] + [self.gen_expr(item)[0] for item in n.items[1:]]
            ty = elem + "[]"
            return ("new %s { %s }" % (self.cs_type(ty), ", ".join(codes)), ty)

        if t is Index:
            base, bty = self.gen_expr(n.target)
            e = elem_of(bty)
            if e not in self.records:
                raise KiteError("Unity 版只支持记录数组的下标", n.line)
            idx, _ = self.gen_expr(n.index)
            return ("GetList(%s, %s, %d)" % (base, idx, n.line), e)

        if t is Slice:
            base, bty = self.gen_expr(n.target)
            if elem_of(bty) not in self.records:
                raise KiteError("Unity 版只支持记录数组的切片", n.line)
            first, _ = self.gen_expr(n.from_)
            last, _ = self.gen_expr(n.to)
            return ("SliceList(%s, %s, %s, %d)" % (base, first, last, n.line), bty)

        if t is Unary:
            code, ty = self.gen_expr(n.operand)
            if n.op == "!":
                return ("B(!(%s != 0))" % code, NUM)
            return ("(-(%s))" % code, NUM)

        if t is BinOp:
            return self.gen_binop(n)

        if t is Field:
            if n.owner is None:
                return self.gen_call(Call(Name(n.fallback or n.name, n.line), [n.target], n.line))
            base, _ = self.gen_expr(n.target)
            field_type = dict(self.records[n.owner].fields)[n.name]
            return ("(%s).%s" % (base, unity_name(n.name)), field_type)

        if t is Call:
            return self.gen_call(n)

        raise KiteError("内部错误：不认识的表达式", getattr(n, "line", 0))

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

        if op in ("-", "*", "/"):
            return ("((%s) %s (%s))" % (l, op, r), NUM)

        if op == "%":
            return ("((%s) %% (%s))" % (l, r), NUM)

        if op == "==":
            return ("B((%s) == (%s))" % (l, r), NUM)
        if op == "!=":
            return ("B((%s) != (%s))" % (l, r), NUM)
        if op in ("<", ">", "<=", ">="):
            return ("B((%s) %s (%s))" % (l, op, r), NUM)

        if op == "&&":
            return ("B((%s != 0) && (%s != 0))" % (l, r), NUM)
        if op == "||":
            return ("B((%s != 0) || (%s != 0))" % (l, r), NUM)

        raise KiteError("不认识的运算符 %s" % op, n.line)

    def gen_call(self, n):
        if not isinstance(n.callee, Name):
            raise KiteError("只能调用有名字的函数", n.line)
        name = n.callee.id

        if name in self.records:
            args = [self.gen_expr(a)[0] for a in n.args]
            return ("new %s(%s)" % (unity_name(name, record=True), ", ".join(args)), name)

        if name == "push":
            target = n.args[0]
            if not isinstance(target, Name):
                raise KiteError("push 要作用在变量上，比如 xs.push(3)", n.line)
            ty, cname = self.lookup(target.id, n.line)
            if elem_of(ty) not in self.records:
                raise KiteError("Unity 版只支持记录数组", n.line)
            code, _ = self.gen_expr(n.args[1])
            return ("%s.Add(%s)" % (cname, code), VOID)

        if name == "len":
            code, ty = self.gen_expr(n.args[0])
            if ty == STR:
                return ("Len(%s)" % code, NUM)
            if elem_of(ty) in self.records:
                return ("((double)(%s).Count)" % code, NUM)
            raise KiteError("Unity 版只支持记录数组", n.line)

        if name == "num":
            return ("Num(%s, %d)" % (self.gen_expr(n.args[0])[0], n.line), NUM)
        if name in SIMPLE_BUILTINS:
            want = ARITY[name]
            if len(n.args) != want:
                raise KiteError("%s 需要 %d 个参数" % (name, want), n.line)
            args = [self.gen_expr(a)[0] for a in n.args]
            return (SIMPLE_BUILTINS[name](args), UNITY_TYPES[name])

        if name in self.rtypes:
            params = self.ptypes[name]
            if len(n.args) != len(params):
                raise KiteError("%s 需要 %d 个参数，给了 %d 个"
                                % (name, len(params), len(n.args)), n.line)
            args = [self.gen_expr(a)[0] for a in n.args]
            return ("%s(%s)" % (unity_name(name, function=True), ", ".join(args)), self.rtypes[name])

        raise KiteError("没有叫「%s」的函数（Unity 版只有 %s）"
                        % (name, "、".join(sorted(SIMPLE_BUILTINS))), n.line)

    # ---------- 语句 ----------

    def as_cond(self, code, line):
        return "(%s != 0)" % code

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
                self.emit("%s %s = %s;" % (self.cs_type(ty), self.new_tmp(), code))
            else:
                self.emit(code + ";")
            return

        if t is Assign:
            code, ty = self.gen_expr(node.value)
            if isinstance(node.target, Index):
                base, bty = self.gen_expr(node.target.target)
                if elem_of(bty) not in self.records:
                    raise KiteError("Unity 版只支持记录数组的下标赋值", node.line)
                idx, _ = self.gen_expr(node.target.index)
                self.emit("SetList(%s, %s, %s, %d);" % (base, idx, code, node.line))
                return
            name = node.target.id
            found = None
            for s in reversed(self.scopes):
                if name in s:
                    found = s[name]
                    break
            if found is None:
                self.declare(name, ty, node.line)
                self.emit("%s %s = %s;" % (self.cs_type(ty), unity_name(name), code))
            else:
                self.emit("%s = %s;" % (found[1], code))
            return

        if t is Say:
            parts = []
            for e in node.exprs:
                code, ty = self.gen_expr(e)
                parts.append(self.to_str(code, ty))
            self.emit("Debug.Log(%s);" % (' + " " + '.join(parts) if len(parts) > 1 else parts[0]))
            return

        if t is If:
            first = True
            for cond, body in node.branches:
                code, cty = self.gen_expr(cond)
                if cty != NUM:
                    raise KiteError("条件要是数字", node.line)
                kw = "if" if first else "else if"
                self.emit("%s (%s)" % (kw, self.as_cond(code, node.line)))
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
            self.emit("bool %s = %s > %s;" % (descending, first, last))
            header = ("for (double %s = %s; Finite(%s) && Finite(%s) && "
                      "(%s ? %s >= %s : %s <= %s); %s = NextCount(%s, %s ? -1 : 1))"
                      % (name, first, first, last, descending, name, last, name, last, name, name, descending))
            ty = NUM
        else:
            code, ty = self.gen_expr(src)
            item = elem_of(ty)
            if item is not None:
                if item not in self.records:
                    raise KiteError("Unity 版只支持记录数组", node.line)
                arr, index = self.new_tmp(), self.new_tmp()
                self.emit("%s %s = %s;" % (self.cs_type(ty), arr, code))
                header = "for (int %s = 0; %s < %s.Count; %s++)" % (index, index, arr, index)
                item_source = "%s[%s]" % (arr, index)
                ty = item
            else:
                limit = self.new_tmp()
                self.emit("double %s = %s;" % (limit, code))
                header = ("for (double %s = 1; Finite(%s) && %s <= %s; %s = NextCount(%s, 1))"
                          % (name, limit, name, limit, name, name))
        self.emit(header)
        self.emit("{")
        self.push()
        self.scopes[-1][key] = (ty, name)
        self.ind += 1
        if item_source is not None:
            self.emit("%s %s = %s;" % (self.cs_type(ty), name, item_source))
        for stmt in node.body.stmts:
            self.gen_stmt(stmt)
        self.ind -= 1
        self.pop()
        self.emit("}")
        self.ind -= 1
        self.emit("}")

    # ---------- 整个文件 ----------

    def gen_record(self, record):
        name = unity_name(record.name, record=True)
        fields = [(self.cs_type(ty), unity_name(field)) for field, ty in record.fields]
        lines = ["    sealed class %s" % name, "    {"]
        for ty, field in fields:
            lines.append("        public readonly %s %s;" % (ty, field))
        params = ", ".join("%s %s" % (ty, field) for ty, field in fields)
        lines.append("        public %s(%s)" % (name, params))
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
            self.scopes[-1][pname] = (ty, unity_name(pname))
        for stmt in fn.body.stmts:
            self.gen_stmt(stmt)
        params = ", ".join("%s %s" % (self.cs_type(t), unity_name(pn))
                           for (pn, _), t in zip(fn.params, self.ptypes[fn.name]))
        head = "%s %s(%s)" % (self.cs_type(self.rtypes[fn.name]), unity_name(fn.name, function=True), params)
        return head, self.out

    def build(self, program):
        funcs = {}
        for stmt in program.stmts:
            if isinstance(stmt, FnDef):
                funcs[stmt.name] = stmt

        top = [s for s in program.stmts if not isinstance(s, (FnDef, RecordDef))]

        lines = ["using System.Collections.Generic;", "using System.Globalization;", "using System.Text.RegularExpressions;",
                 "using BigInteger = System.Numerics.BigInteger;", "using UnityEngine;", "",
                 "// 由 kite 自动生成。改游戏请改 .kite 源文件。",
                 "public class %s : MonoBehaviour" % self.class_name,
                 "{"]

        for special in ("start", "update"):
            if special in funcs:
                fn = funcs[special]
                if fn.params:
                    raise KiteError("%s 不能带参数" % special, fn.line)
                if self.rtypes[special] != VOID:
                    raise KiteError("%s 不能有返回值" % special, fn.line)

        # Start runs top-level code before invoking the user hook.
        self.out = []
        self.scopes = [{}]
        self.ind = 2
        for stmt in top:
            self.gen_stmt(stmt)
        if "start" in funcs:
            self.emit("%s();" % unity_name("start", function=True))
        start_body = self.out

        lines.append("    Rigidbody2D _rb;")
        lines.append("    Collider2D _col;")
        lines.append("")
        lines.append("    void Start()")
        lines.append("    {")
        lines.append("        _rb = GetComponent<Rigidbody2D>();")
        lines.append("        _col = GetComponent<Collider2D>();")
        lines.append("        if (_rb != null) _rb.freezeRotation = true;")
        lines.extend(start_body)
        lines.append("    }")
        lines.append("")
        lines.append("    void Update()")
        lines.append("    {")
        if "update" in funcs:
            lines.append("        %s();" % unity_name("update", function=True))
        lines.append("    }")
        lines.append("")

        for record in self.records.values():
            lines.extend(self.gen_record(record))

        # 用户函数
        for fn in funcs.values():
            self.out = []
            head, body = self.gen_function(fn)
            lines.append("    " + head)
            lines.append("    {")
            lines.extend(body)
            lines.append("    }")
            lines.append("")

        lines.append(HELPERS)
        lines.append("}")
        return "\n".join(lines)


HELPERS = r'''
    // ---------------- kite 内置 ----------------

    static double B(bool v) { return v ? 1.0 : 0.0; }
    static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
    static readonly Regex Decimal = new Regex(@"\A[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\z");

    static double Num(string s, int line)
    {
        s = s.Trim(' ', '\t', '\n', '\v', '\f', '\r');
        if (s.Length == 0) return 0;
        double value;
        if (Decimal.IsMatch(s) && double.TryParse(s, NumberStyles.Float, Invariant, out value) && Finite(value))
            return value;
        throw new System.FormatException("第 " + line + " 行：不能转成数字");
    }

    static bool Finite(double v) { return !double.IsNaN(v) && !double.IsInfinity(v); }

    static int Index(double i, int n, int line)
    {
        if (!Finite(i)) throw new System.Exception("第 " + line + " 行：下标要是有限数字");
        double k = System.Math.Truncate(i);
        if (k == 0) throw new System.Exception("第 " + line + " 行：下标从 1 开始数，没有第 0 个");
        if (k < 0) k = n + k + 1;
        if (k < 1 || k > n)
            throw new System.Exception("第 " + line + " 行：越界（下标 " + S(i) + "，长度 " + n + "，从 1 开始数）");
        return (int)k - 1;
    }

    static T GetList<T>(List<T> a, double i, int line)
    {
        return a[Index(i, a.Count, line)];
    }

    static void SetList<T>(List<T> a, double i, T value, int line)
    {
        a[Index(i, a.Count, line)] = value;
    }

    static List<T> SliceList<T>(List<T> a, double first, double last, int line)
    {
        if (!Finite(first) || !Finite(last))
            throw new System.Exception("第 " + line + " 行：切片下标要是有限数字");
        double from = System.Math.Truncate(first), to = System.Math.Truncate(last);
        if (from < 0) from = a.Count + from + 1;
        if (to < 0) to = a.Count + to + 1;
        from = System.Math.Max(1, System.Math.Min((double)a.Count + 1, from));
        to = System.Math.Max(0, System.Math.Min(a.Count, to));
        if (from > to) return new List<T>();
        return a.GetRange((int)from - 1, (int)(to - from + 1));
    }

    static double NextCount(double v, double step)
    {
        double next = v + step;
        return next == v ? double.NaN : next;
    }

    static string S(double v)
    {
        if (double.IsNaN(v)) return "nan";
        if (double.IsInfinity(v)) return v < 0 ? "-inf" : "inf";
        if (v == System.Math.Truncate(v) && System.Math.Abs(v) < 1e15) return ((long)v).ToString(Invariant);
        string sign = v < 0 ? "-" : "";
        // Format the exact binary value with 15 significant decimal digits, ties to even.
        long bits = System.BitConverter.DoubleToInt64Bits(System.Math.Abs(v));
        int field = (int)(bits >> 52);
        BigInteger m = (bits & ((1L << 52) - 1)) | (field != 0 ? 1L << 52 : 0L);
        int power = (field == 0 ? 1 : field) - 1075;
        string digits = (power >= 0 ? m << power : m * BigInteger.Pow(5, -power)).ToString(Invariant);
        int exponent = digits.Length - 1 + System.Math.Min(0, power);
        string rounded = digits.Substring(0, System.Math.Min(15, digits.Length));
        if (digits.Length > 15 && (digits[15] > '5' ||
            (digits[15] == '5' && (digits.Substring(16).TrimEnd('0').Length > 0 || (rounded[14] - '0') % 2 != 0))))
        {
            rounded = (long.Parse(rounded, Invariant) + 1).ToString(Invariant);
            if (rounded.Length > 15) exponent++;
        }
        rounded = rounded.TrimEnd('0');
        if (exponent < -4 || exponent >= 15)
            return sign + rounded[0] + (rounded.Length > 1 ? "." + rounded.Substring(1) : "") + "e" + exponent.ToString(Invariant);
        if (exponent < 0) return sign + "0." + new string('0', -exponent - 1) + rounded;
        if (rounded.Length <= exponent + 1) return sign + rounded.PadRight(exponent + 1, '0');
        return sign + rounded.Insert(exponent + 1, ".");
    }

    static string S(string v) { return v; }
    static double Len(string s)
    {
        int count = 0;
        for (int i = 0; i < s.Length; i++, count++)
            if (i + 1 < s.Length && char.IsSurrogatePair(s[i], s[i + 1])) i++;
        return count;
    }

    double X() { return transform.position.x; }
    double Y() { return transform.position.y; }

    void SetPos(double x, double y)
    {
        transform.position = new Vector3((float)x, (float)y, transform.position.z);
    }

    void MoveX(double v)
    {
        if (_rb == null) return;
        _rb.velocity = new Vector2((float)v, _rb.velocity.y);
    }

    void Jump(double v)
    {
        if (_rb == null) return;
        _rb.velocity = new Vector2(_rb.velocity.x, (float)v);
    }

    double Key(string name)
    {
        KeyCode k;
        switch (name)
        {
            case "left":  k = KeyCode.LeftArrow; break;
            case "right": k = KeyCode.RightArrow; break;
            case "up":    k = KeyCode.UpArrow; break;
            case "down":  k = KeyCode.DownArrow; break;
            case "space": k = KeyCode.Space; break;
            case "a":     k = KeyCode.A; break;
            case "d":     k = KeyCode.D; break;
            case "w":     k = KeyCode.W; break;
            case "s":     k = KeyCode.S; break;
            default:      k = KeyCode.Space; break;
        }
        return Input.GetKey(k) ? 1.0 : 0.0;
    }

    double OnGround()
    {
        if (_col == null) return 0;
        Vector2 feet = new Vector2(_col.bounds.center.x, _col.bounds.min.y);
        RaycastHit2D hit = Physics2D.Raycast(feet, Vector2.down, 0.12f);
        return (hit.collider != null && hit.collider != _col) ? 1.0 : 0.0;
    }
'''


def class_name_for(path):
    base = os.path.splitext(os.path.basename(path))[0]
    parts = [p for p in base.replace("-", "_").split("_") if p]
    name = "".join(p[:1].upper() + p[1:] for p in parts) or "KiteGame"
    name = "".join(ch for ch in name if ch.isalnum())
    if not name or name[0].isdigit():
        name = "Kite" + name
    return name


def generate(src, path):
    program = load_program(src, path)
    require_backend(program, "Unity")
    typer = Typer(program, extra=UNITY_TYPES)
    ptypes, rtypes = typer.run()

    gen = UnityGen(ptypes, rtypes, typer.records, class_name_for(path))
    return gen.build(program)


def main(argv):
    if len(argv) < 2:
        print("用法：python3 kite_unity.py 游戏.kite")
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
    out = os.path.join(os.path.dirname(os.path.abspath(path)),
                       class_name_for(path) + ".cs")
    with open(out, "w", encoding="utf-8") as f:
        f.write(code)
    print("已生成 " + out, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
