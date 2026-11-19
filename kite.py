#!/usr/bin/env python3
"""
kite —— 一门简单的语言，翻译成 C，再用 gcc 编译。

只有两种值：数字、文本。
函数不用写类型，编译器自己推；推不出来时你可以手写标注。

    python3 kite.py prog.kite            # 生成 prog.c
    python3 kite.py prog.kite --run      # 生成 + 编译 + 运行
"""

import argparse
import os
import re
import shutil
import sys
import subprocess

KEYWORDS = {
    "p", "if", "elif", "else", "rp", "ut", "in", "fn", "ret",
    "break", "continue", "true", "false",
}

TYPE_NAMES = {"number", "string"}

RETIRED = {
    "while": "条件循环现在写成「rp ut 条件」。",
    "for": "循环现在统一用「rp」：rp 5 / rp 1..10 / rp 数组。",
    "as": "嵌套循环现在写成「rp i in 1..10」，不再用 as。",
    "loop": "写成「rp 次数」。",
    "repeat": "写成「rp 次数」。",
    "say": "打印用「p」。",
    "let": "直接写「x = 1」就会创建变量。",
}

ESC = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}
LBRACE = "\ue000"
RBRACE = "\ue001"

NUM = "number"
STR = "string"
UNK = "?"
VOID = "void"


class KiteError(Exception):
    def __init__(self, msg, line=0, path=None):
        super().__init__(msg)
        self.msg = msg
        self.path = path
        self.line = line


def type_cn(t):
    return {"number": "数字", "string": "文本", "?": "还不知道", "void": "没有值"}.get(t, t)


def elem_of(t):
    return t[:-2] if t.endswith("[]") else None


def array_of(t):
    return t + "[]"


def is_matrix(t):
    return t.endswith("[][]")


# ============================================================ 词法

class Token:
    __slots__ = ("kind", "value", "line")

    def __init__(self, kind, value, line):
        self.kind = kind
        self.value = value
        self.line = line

    def __repr__(self):
        return "%s(%r)" % (self.kind, self.value)


def tokenize(src):
    if "\0" in src:
        line = src.count("\n", 0, src.index("\0")) + 1
        raise KiteError("源文件不能含 NUL 字符", line)
    toks = []
    i, n, line = 0, len(src), 1
    indents = [0]
    at_line_start = True

    def emit(kind, value="", ln=None):
        ln = line if ln is None else ln
        if kind == "NEWLINE" and toks and toks[-1].kind == "NEWLINE":
            return
        toks.append(Token(kind, value, ln))

    while i < n:
        if at_line_start:
            start_line = line
            width = 0
            while i < n and src[i] in " \t":
                width += 4 if src[i] == "\t" else 1
                i += 1
            if i >= n:
                break
            if src[i] == "\n":
                i += 1
                line += 1
                continue
            if src[i] == "#":
                while i < n and src[i] != "\n":
                    i += 1
                continue
            if not toks and width > 0:
                raise KiteError("文件第一行不能缩进", start_line)
            if width > indents[-1]:
                indents.append(width)
                emit("INDENT", "", start_line)
            elif width < indents[-1]:
                while len(indents) > 1 and width < indents[-1]:
                    indents.pop()
                    emit("DEDENT", "", start_line)
                if width != indents[-1]:
                    raise KiteError("缩进对不齐（这一行和上面的块不一致）", start_line)
            at_line_start = False
            continue

        c = src[i]

        if c in " \t\r":
            i += 1
            continue
        if c == "\n":
            emit("NEWLINE")
            i += 1
            line += 1
            at_line_start = True
            continue
        if c == "#":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c.isdigit():
            start = i
            while i < n and src[i].isdigit():
                i += 1
            is_float = False
            if i + 1 < n and src[i] == "." and src[i + 1].isdigit():
                is_float = True
                i += 1
                while i < n and src[i].isdigit():
                    i += 1
            raw = src[start:i]
            emit("NUMBER", float(raw) if is_float else int(raw))
            continue
        if c in "\"'":
            quote = c
            start_line = line
            i += 1
            buf = []
            while True:
                if i >= n:
                    raise KiteError("文本没有闭合（少了引号）", start_line)
                ch = src[i]
                if ch == "\n":
                    buf.append(ch)
                    i += 1
                    line += 1
                    continue
                if ch == quote:
                    i += 1
                    break
                if ch == "\\" and i + 1 < n:
                    i += 1
                    nxt = src[i]
                    if nxt == "{":
                        buf.append(LBRACE)
                    elif nxt == "}":
                        buf.append(RBRACE)
                    else:
                        buf.append(ESC.get(nxt, nxt))
                else:
                    buf.append(ch)
                i += 1
            emit("TEXT", "".join(buf), start_line)
            continue
        if c.isalpha() or c == "_":
            start = i
            while i < n and (src[i].isalnum() or src[i] == "_"):
                i += 1
            word = src[start:i]
            emit("KW" if word in KEYWORDS else "NAME", word)
            continue

        two = src[i:i + 2]
        if two in ("==", "!=", "<=", ">=", "..", "&&", "||", "->"):
            emit("OP", two)
            i += 2
            continue
        if c in "+-*/%=<>()[],:!&|.":
            emit("OP", c)
            i += 1
            continue
        raise KiteError("看不懂这个字符：%r" % c, line)

    if toks and toks[-1].kind != "NEWLINE":
        emit("NEWLINE")
    while len(indents) > 1:
        indents.pop()
        emit("DEDENT")
    toks.append(Token("EOF", "", line))
    return toks


# ============================================================ 语法树

class Node:
    __slots__ = ("line", "source_path")


class Num(Node):
    __slots__ = ("value",)

    def __init__(self, value, line=0):
        self.value = value
        self.line = line


class Text(Node):
    __slots__ = ("value",)

    def __init__(self, value, line=0):
        self.value = value
        self.line = line


class Interp(Node):
    __slots__ = ("parts",)

    def __init__(self, parts, line=0):
        self.parts = parts
        self.line = line


class Name(Node):
    __slots__ = ("id",)

    def __init__(self, id, line=0):
        self.id = id
        self.line = line


class ListLit(Node):
    __slots__ = ("items",)

    def __init__(self, items, line=0):
        self.items = items
        self.line = line


class BinOp(Node):
    __slots__ = ("op", "left", "right")

    def __init__(self, op, left, right, line=0):
        self.op = op
        self.left = left
        self.right = right
        self.line = line


class Unary(Node):
    __slots__ = ("op", "operand")

    def __init__(self, op, operand, line=0):
        self.op = op
        self.operand = operand
        self.line = line


class Call(Node):
    __slots__ = ("callee", "args")

    def __init__(self, callee, args, line=0):
        self.callee = callee
        self.args = args
        self.line = line


class Slice(Node):
    __slots__ = ("target", "from_", "to")

    def __init__(self, target, from_, to, line=0):
        self.target = target
        self.from_ = from_
        self.to = to
        self.line = line


class Index(Node):
    __slots__ = ("target", "index")

    def __init__(self, target, index, line=0):
        self.target = target
        self.index = index
        self.line = line


class Block(Node):
    __slots__ = ("stmts",)

    def __init__(self, stmts, line=0):
        self.stmts = stmts
        self.line = line


class Assign(Node):
    __slots__ = ("target", "value")

    def __init__(self, target, value, line=0):
        self.target = target
        self.value = value
        self.line = line


class Say(Node):
    __slots__ = ("exprs",)

    def __init__(self, exprs, line=0):
        self.exprs = exprs
        self.line = line


class If(Node):
    __slots__ = ("branches", "orelse")

    def __init__(self, branches, orelse, line=0):
        self.branches = branches
        self.orelse = orelse
        self.line = line


class Loop(Node):
    """rp：mode 是 until / auto；auto 时看 source 是数字、范围还是数组"""
    __slots__ = ("mode", "source", "name", "body")

    def __init__(self, mode, source, name, body, line=0):
        self.mode = mode
        self.source = source
        self.name = name
        self.body = body
        self.line = line


class FnDef(Node):
    __slots__ = ("name", "params", "ret", "body")

    def __init__(self, name, params, ret, body, line=0):
        self.name = name
        self.params = params    # [(名字, 类型或 None)]
        self.ret = ret          # 类型或 None
        self.body = body
        self.line = line


class ExternDef(Node):
    __slots__ = ("name", "params", "ret", "symbol")

    def __init__(self, name, params, ret, symbol, line):
        self.name, self.params, self.ret, self.symbol, self.line = name, params, ret, symbol, line


class RecordDef(Node):
    __slots__ = ("name", "fields")

    def __init__(self, name, fields, line):
        self.name, self.fields, self.line = name, fields, line


class Field(Node):
    __slots__ = ("target", "name", "owner", "fallback")

    def __init__(self, target, name, line):
        self.target, self.name, self.line = target, name, line
        self.owner = None
        self.fallback = None


class Return(Node):
    __slots__ = ("expr",)

    def __init__(self, expr, line=0):
        self.expr = expr
        self.line = line


class Break(Node):
    __slots__ = ()

    def __init__(self, line=0):
        self.line = line


class Continue(Node):
    __slots__ = ()

    def __init__(self, line=0):
        self.line = line


class ExprStmt(Node):
    __slots__ = ("expr",)

    def __init__(self, expr, line=0):
        self.expr = expr
        self.line = line


# ============================================================ 语法分析

class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.pos = 0

    def peek(self, k=0):
        return self.toks[min(self.pos + k, len(self.toks) - 1)]

    def check(self, kind, value=None):
        t = self.peek()
        return t.kind == kind and (value is None or t.value == value)

    def advance(self):
        t = self.toks[self.pos]
        if self.pos < len(self.toks) - 1:
            self.pos += 1
        return t

    def match(self, kind, value=None):
        if self.check(kind, value):
            return self.advance()
        return None

    def expect(self, kind, value=None):
        t = self.peek()
        if not (t.kind == kind and (value is None or t.value == value)):
            want = value if value is not None else kind
            got = t.value if t.value != "" else t.kind
            raise KiteError("这里应该是 %s，实际是 %r" % (want, got), t.line)
        return self.advance()

    def skip_newlines(self):
        while self.match("NEWLINE"):
            pass

    def parse_program(self):
        self.skip_newlines()
        stmts = []
        while not self.check("EOF"):
            stmts.append(self.parse_statement())
            self.skip_newlines()
        return Block(stmts, 1)

    def parse_block(self):
        if not self.check("NEWLINE"):
            raise KiteError("这个块要换行并缩进", self.peek().line)
        self.advance()
        self.skip_newlines()
        if not self.check("INDENT"):
            raise KiteError("这个块的缩进还不够", self.peek().line)
        self.advance()
        self.skip_newlines()
        stmts = []
        while not (self.check("DEDENT") or self.check("EOF")):
            stmts.append(self.parse_statement())
            self.skip_newlines()
        if not stmts:
            raise KiteError("块里是空的", self.peek().line)
        self.match("DEDENT")
        return Block(stmts)

    def parse_symbol(self):
        token = self.expect("NAME")
        if self.check("OP", ":") and self.peek(1).value == ":":
            self.advance()
            self.advance()
            return token.value + "::" + self.expect("NAME").value
        return token.value

    def parse_type(self):
        typ = self.parse_symbol()
        if self.match("OP", "["):
            self.expect("OP", "]")
            return array_of(typ)
        return typ

    def parse_record(self):
        line = self.advance().line
        name = self.expect("NAME").value
        self.expect("NEWLINE")
        self.expect("INDENT")
        fields = []
        while not self.check("DEDENT"):
            field = self.expect("NAME")
            self.expect("OP", ":")
            typ = self.parse_type()
            if elem_of(typ) is not None:
                raise KiteError("记录字段类型不能是数组", field.line)
            fields.append((field.value, typ))
            self.expect("NEWLINE")
        self.expect("DEDENT")
        return RecordDef(name, fields, line)

    def parse_statement(self):
        t = self.peek()
        if t.kind == "INDENT":
            raise KiteError("这一行缩进太多了", t.line)
        if t.kind == "DEDENT":
            raise KiteError("这一行缩进不够", t.line)
        if t.kind == "NAME" and t.value == "record" and self.peek(1).kind == "NAME":
            return self.parse_record()
        if (t.kind == "NAME" and t.value == "extern" and self.peek(1).value == "c"
                and self.peek(2).value == "fn"):
            return self.parse_extern()
        if t.kind == "NAME" and t.value in RETIRED:
            raise KiteError("「%s」这一版已经没有了。%s"
                            % (t.value, RETIRED[t.value]), t.line)
        if t.kind == "KW":
            kw = t.value
            if kw == "p":
                return self.parse_say()
            if kw == "if":
                return self.parse_if()
            if kw == "rp":
                return self.parse_loop()

            if kw == "fn":
                return self.parse_fn()
            if kw == "ret":
                line = self.advance().line
                if self.check("NEWLINE") or self.check("EOF") or self.check("DEDENT"):
                    return Return(None, line)
                return Return(self.parse_expression(), line)
            if kw == "break":
                return Break(self.advance().line)
            if kw == "continue":
                return Continue(self.advance().line)
        return self.parse_assign()

    def parse_assign(self):
        line = self.peek().line
        expr = self.parse_expression()
        if self.check("OP", "="):
            self.advance()
            if isinstance(expr, Field):
                raise KiteError("记录字段不能直接修改，请构造一条新记录", line)
            if not isinstance(expr, (Name, Index)):
                raise KiteError("等号左边只能是一个变量名", line)
            return Assign(expr, self.parse_expression(), line)
        return ExprStmt(expr, line)

    def parse_say(self):
        line = self.advance().line
        exprs = [self.parse_expression()]
        while self.match("OP", ","):
            exprs.append(self.parse_expression())
        return Say(exprs, line)

    def parse_if(self):
        line = self.advance().line
        branches = [(self.parse_expression(), self.parse_block())]
        while self.check("KW", "elif"):
            self.advance()
            branches.append((self.parse_expression(), self.parse_block()))
        orelse = None
        if self.check("KW", "else"):
            self.advance()
            orelse = self.parse_block()
        return If(branches, orelse, line)

    def parse_loop(self):
        line = self.advance().line
        if self.check("KW", "ut"):
            self.advance()
            cond = self.parse_expression()
            return Loop("until", cond, None, self.parse_block(), line)
        if (self.check("NAME") and self.peek(1).kind == "KW"
                and self.peek(1).value == "in"):
            name = self.advance().value
            self.advance()
            source = self.parse_expression()
            return Loop("auto", source, name, self.parse_block(), line)
        source = self.parse_expression()
        if self.check("NAME", "as"):
            raise KiteError("「as」已经改成「in」了：写成 rp i in 1..5",
                            self.peek().line)
        return Loop("auto", source, None, self.parse_block(), line)

    def parse_extern(self):
        line = self.advance().line
        self.expect("NAME", "c")
        self.expect("KW", "fn")
        name, params, ret = self.parse_fn_signature()
        self.expect("OP", "=")
        token = self.expect("TEXT")
        self.expect("NEWLINE")
        return ExternDef(name, params, ret, token.value, line)

    def parse_fn(self):
        line = self.advance().line
        name, params, ret = self.parse_fn_signature()
        return FnDef(name, params, ret, self.parse_block(), line)

    def parse_fn_signature(self):
        name = self.expect("NAME").value
        self.expect("OP", "(")
        params = []
        if not self.check("OP", ")"):
            while True:
                pname = self.expect("NAME").value
                ptype = None
                if self.match("OP", ":"):
                    ptype = self.parse_type()
                params.append((pname, ptype))
                if not self.match("OP", ","):
                    break
        self.expect("OP", ")")
        ret = None
        if self.match("OP", "->"):
            ret = self.parse_type()
        return name, params, ret

    # -- 表达式

    def parse_expression(self):
        return self.parse_or()

    def parse_or(self):
        node = self.parse_and()
        while self.check("OP", "||"):
            line = self.advance().line
            node = BinOp("||", node, self.parse_and(), line)
        return node

    def parse_and(self):
        node = self.parse_not()
        while self.check("OP", "&&"):
            line = self.advance().line
            node = BinOp("&&", node, self.parse_not(), line)
        return node

    def parse_not(self):
        if self.check("OP", "!"):
            line = self.advance().line
            return Unary("!", self.parse_not(), line)
        return self.parse_comparison()

    def parse_range(self):
        node = self.parse_additive()
        while self.check("OP", ".."):
            op = self.advance()
            node = BinOp("..", node, self.parse_additive(), op.line)
        return node

    def parse_comparison(self):
        node = self.parse_range()
        ops = ("==", "!=", "<", ">", "<=", ">=")
        while self.peek().kind == "OP" and self.peek().value in ops:
            op = self.advance()
            node = BinOp(op.value, node, self.parse_range(), op.line)
        return node

    def parse_additive(self):
        node = self.parse_multiplicative()
        while self.check("OP", "+") or self.check("OP", "-"):
            op = self.advance()
            node = BinOp(op.value, node, self.parse_multiplicative(), op.line)
        return node

    def parse_multiplicative(self):
        node = self.parse_unary()
        while self.peek().kind == "OP" and self.peek().value in ("*", "/", "%"):
            op = self.advance()
            node = BinOp(op.value, node, self.parse_unary(), op.line)
        return node

    def parse_unary(self):
        if self.check("OP", "-"):
            op = self.advance()
            return Unary("-", self.parse_unary(), op.line)
        return self.parse_postfix()

    def parse_postfix(self):
        node = self.parse_primary()
        while True:
            if self.check("OP", "("):
                line = self.advance().line
                args = []
                if not self.check("OP", ")"):
                    args.append(self.parse_expression())
                    while self.match("OP", ","):
                        if self.check("OP", ")"):
                            break
                        args.append(self.parse_expression())
                self.expect("OP", ")")
                node = Call(node, args, line)
            elif self.check("OP", "."):
                line = self.advance().line
                if not self.check("NAME"):
                    raise KiteError("点号后面要写一个函数名，比如 xs.len", line)
                tname = self.advance()
                if not self.check("OP", "("):
                    node = Field(node, tname.value, tname.line)
                    continue
                args = [node]
                if self.check("OP", "("):
                    self.advance()
                    if not self.check("OP", ")"):
                        args.append(self.parse_expression())
                        while self.match("OP", ","):
                            if self.check("OP", ")"):
                                break
                            args.append(self.parse_expression())
                    self.expect("OP", ")")
                node = Call(Name(tname.value, tname.line), args, line)
            elif self.check("OP", "["):
                line = self.advance().line
                idx = self.parse_expression()
                self.expect("OP", "]")
                if isinstance(idx, BinOp) and idx.op == "..":
                    node = Slice(node, idx.left, idx.right, line)
                else:
                    node = Index(node, idx, line)
            else:
                break
        return node

    def parse_primary(self):
        t = self.peek()
        if t.kind == "NUMBER":
            self.advance()
            return Num(t.value, t.line)
        if t.kind == "TEXT":
            self.advance()
            return self.parse_text(t)
        if t.kind == "NAME":
            return Name(self.parse_symbol(), t.line)
        if t.kind == "KW":
            if t.value == "true":
                self.advance()
                return Num(1, t.line)
            if t.value == "false":
                self.advance()
                return Num(0, t.line)
        if t.kind == "OP" and t.value == "(":
            self.advance()
            expr = self.parse_expression()
            self.expect("OP", ")")
            return expr
        if t.kind == "OP" and t.value == "[":
            line = self.advance().line
            items = []
            if not self.check("OP", "]"):
                items.append(self.parse_expression())
                while self.match("OP", ","):
                    if self.check("OP", "]"):
                        break
                    items.append(self.parse_expression())
            self.expect("OP", "]")
            return ListLit(items, line)
        got = t.value if t.value != "" else t.kind
        raise KiteError("这里看不懂：%r" % (got,), t.line)

    def parse_text(self, tok):
        raw = tok.value
        clean = raw.replace(LBRACE, "{").replace(RBRACE, "}")
        if LBRACE not in raw and RBRACE not in raw and "{" not in raw:
            return Text(clean, tok.line)

        parts = []
        buf = []
        i = 0
        while i < len(raw):
            ch = raw[i]
            if ch == LBRACE:
                buf.append("{")
                i += 1
                continue
            if ch == RBRACE:
                buf.append("}")
                i += 1
                continue
            if ch != "{":
                buf.append(ch)
                i += 1
                continue

            depth = 1
            j = i + 1
            inner = []
            while j < len(raw):
                if raw[j] == LBRACE:
                    inner.append("{")
                elif raw[j] == RBRACE:
                    inner.append("}")
                elif raw[j] == "{":
                    depth += 1
                    inner.append("{")
                elif raw[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                    inner.append("}")
                else:
                    inner.append(raw[j])
                j += 1
            if depth != 0:
                raise KiteError("文本里的 { 没有闭合", tok.line)

            code = "".join(inner).strip()
            if code:
                if buf:
                    parts.append(Text("".join(buf), tok.line))
                    buf = []
                try:
                    tokens = tokenize(code)
                    for token in tokens:
                        token.line += tok.line - 1 + raw.count("\n", 0, i)
                    sub = Parser(tokens)
                    parts.append(sub.parse_expression())
                    sub.skip_newlines()
                    sub.expect("EOF")
                except KiteError:
                    raise KiteError("花括号里「%s」不是一个完整表达式" % code, tok.line)
            i = j + 1

        if buf:
            parts.append(Text("".join(buf), tok.line))
        if not parts:
            return Text("", tok.line)
        return Interp(parts, tok.line)


# ============================================================ 类型推断

_SCALAR = (NUM, STR)
_ARRAY = (array_of(NUM), array_of(STR))
_SIZED = (STR, *_ARRAY, *(array_of(t) for t in _ARRAY))
_PRINTABLE = (NUM, *_SIZED)

# 每项是可用的参数列表。重载也用于检查数组和元素类型是否匹配。
_BUILTIN_PARAMS = {
    "len": ((_SIZED,),), "txt": ((_PRINTABLE,),), "num": ((STR,),),
    "up": ((STR,),), "low": ((STR,),), "trim": ((STR,),), "read": ((STR,),),
    "write": ((STR, STR),), "ask": ((), (STR,)), "rand": ((NUM,),), "seed": ((NUM,),),
    "mat": ((NUM, NUM, _SCALAR),),
    "abs": ((NUM,),), "floor": ((NUM,),), "round": ((NUM,),), "sqrt": ((NUM,),),
    "pow": ((NUM, NUM),), "rep": ((STR, NUM),), "find": ((STR, STR),),
    "sub": ((STR, NUM, NUM),), "repl": ((STR, STR, STR),),
    "now": ((),), "date": ((),), "ts": ((),), "exist": ((STR,),),
    "del": ((STR,),), "form": ((STR,),), "html": ((STR,),),
    "hex": ((NUM,),), "bin": ((NUM,),),
    **{name: ((_ARRAY[0],),) for name in ("sum", "avg", "min", "max")},
    "sort": ((_ARRAY,),), "join": ((_ARRAY,), (_ARRAY, STR)),
    "split": ((STR,), (STR, STR)),
    **{name: tuple(zip(_ARRAY, _SCALAR)) for name in ("times", "has", "push")},
    "serve": ((NUM, "处理函数"),),
}

# kite_unity.UNITY_TYPES 提供返回类型，这里补充各函数的参数类型。
_UNITY_PARAMS = {
    "key": ((STR,),), "on_ground": ((),), "move_x": ((NUM,),), "jump": ((NUM,),),
    "x": ((),), "y": ((),), "set_pos": ((NUM, NUM),),
    "txt": ((_SCALAR,),), "len": ((STR,),),
}


class Typer:
    """检查类型和控制流，并反复遍历直到函数签名稳定。"""

    def __init__(self, program, extra=None):
        self.program = program
        self.extra = extra or {}
        self.funcs = {}
        self.ptypes = {}
        self.rtypes = {}
        self.records = {}
        for stmt in program.stmts:
            if isinstance(stmt, RecordDef):
                if stmt.name in self.records or stmt.name in TYPE_NAMES or stmt.name in BUILTINS or stmt.name in self.extra:
                    raise KiteError("记录名「%s」已被使用" % stmt.name, stmt.line, getattr(stmt, "source_path", None))
                self.records[stmt.name] = stmt
        self.record_order = self.order_records()
        self.record_array_types = tuple(map(array_of, self.records))
        self.value_types = (*_PRINTABLE, *self.records, *self.record_array_types)
        self.return_types = (*_SCALAR, *self.records)

        for s in program.stmts:
            if isinstance(s, (FnDef, ExternDef)):
                if isinstance(s, ExternDef):
                    self.validate_extern(s)
                if s.name in self.funcs:
                    raise KiteError("函数「%s」定义了两次" % s.name, s.line)
                if s.name in BUILTINS or s.name in self.extra or s.name in self.records:
                    raise KiteError("「%s」是内置函数名，换一个" % s.name, s.line)
                if s.ret is not None:
                    if elem_of(s.ret) is not None:
                        raise KiteError("函数不能返回数组", s.line, getattr(s, "source_path", None))
                    self.check_annotation(s.ret, s)
                for _, annotation in s.params:
                    if annotation is not None and annotation not in self.record_array_types:
                        self.check_annotation(annotation, s)
                self.funcs[s.name] = s
                self.ptypes[s.name] = [t if t else UNK for _, t in s.params]
                self.rtypes[s.name] = s.ret or (UNK if self.has_value_return(s.body) else VOID)
        self.validate_external_signatures()

        self.changed = False
        self.reset_scope()

    @staticmethod
    def validate_extern(decl):
        path = getattr(decl, "source_path", None)
        if decl.ret != NUM or any(typ != NUM for _, typ in decl.params):
            raise KiteError("extern c 的参数和返回值必须显式标注 number", decl.line, path)
        if len({name for name, _ in decl.params}) != len(decl.params):
            raise KiteError("extern c 的参数名不能重复", decl.line, path)
        if (not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", decl.symbol)
                or decl.symbol.startswith(("rt_", "kite_")) or decl.symbol == "main"):
            raise KiteError("无效或保留的 C 符号名", decl.line, path)

    def validate_external_signatures(self):
        seen = {}
        for decl in self.funcs.values():
            if isinstance(decl, ExternDef):
                arity = len(decl.params)
                if decl.symbol in seen and seen[decl.symbol] != arity:
                    raise KiteError("同一 C 符号的参数数量不一致", decl.line, getattr(decl, "source_path", None))
                seen[decl.symbol] = arity

    def check_annotation(self, annotation, node):
        if isinstance(node, RecordDef) and elem_of(annotation) is not None:
            raise KiteError("记录字段类型不能是数组", node.line, getattr(node, "source_path", None))
        if annotation not in TYPE_NAMES and annotation not in self.records:
            raise KiteError("没有叫「%s」的类型" % annotation, node.line, getattr(node, "source_path", None))

    def order_records(self):
        ordered, active, seen = [], set(), set()

        def visit(record):
            if record.name in active:
                raise KiteError("记录字段不能递归引用自身" , record.line, getattr(record, "source_path", None))
            if record.name in seen:
                return
            active.add(record.name)
            fields = set()
            for field, annotation in record.fields:
                if field in fields:
                    raise KiteError("记录字段「%s」重复了" % field, record.line, getattr(record, "source_path", None))
                fields.add(field)
                self.check_annotation(annotation, record)
                if annotation in self.records:
                    visit(self.records[annotation])
            active.remove(record.name)
            seen.add(record.name)
            ordered.append(record)

        for record in self.records.values():
            visit(record)
        return ordered

    @staticmethod
    def has_value_return(block):
        for stmt in block.stmts:
            if isinstance(stmt, Return) and stmt.expr is not None:
                return True
            if isinstance(stmt, If):
                if any(Typer.has_value_return(body) for _, body in stmt.branches):
                    return True
                if stmt.orelse is not None and Typer.has_value_return(stmt.orelse):
                    return True
            if isinstance(stmt, Loop) and Typer.has_value_return(stmt.body):
                return True
        return False

    @staticmethod
    def block_returns(block):
        for stmt in block.stmts:
            if isinstance(stmt, Return):
                return stmt.expr is not None
            if (isinstance(stmt, If) and stmt.orelse is not None
                    and all(Typer.block_returns(body) for _, body in stmt.branches)
                    and Typer.block_returns(stmt.orelse)):
                return True
        return False

    def reset_scope(self, fn=None):
        self.scopes = [{}]
        self.borrowed = [set()]
        self.cur = fn
        self.loop_depth = 0

    # -- 作用域

    def push(self):
        self.scopes.append({})
        self.borrowed.append(set())

    def pop(self):
        self.scopes.pop()
        self.borrowed.pop()

    def check_variable_name(self, name, line):
        if name in self.funcs or name in BUILTINS or name in self.extra or name in self.records:
            raise KiteError("「%s」是函数名，不能用作变量名" % name, line)

    def declare(self, name, t, line):
        self.check_variable_name(name, line)
        if name in self.scopes[-1]:
            raise KiteError("名字「%s」已经用过了" % name, line)
        self.scopes[-1][name] = t

    def lookup(self, name, line):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        raise KiteError("「%s」还没有定义" % name, line)

    def is_borrowed(self, name):
        for scope, borrowed in zip(reversed(self.scopes), reversed(self.borrowed)):
            if name in scope:
                return name in borrowed
        return False

    def expect_type(self, actual, expected, line, what):
        options = expected if isinstance(expected, tuple) else (expected,)
        if actual == UNK or actual in options:
            return
        raise KiteError("%s要%s，实际是%s"
                        % (what, "或".join(map(type_cn, options)), type_cn(actual)), line)

    def number(self, expr, what):
        self.expect_type(self.type_of(expr), NUM, expr.line, what)

    # -- 合并

    def merge(self, a, b, line, what):
        if a == UNK:
            return b
        if b == UNK:
            return a
        if a == b:
            return a
        ea, eb = elem_of(a), elem_of(b)
        if ea is not None and eb is not None:
            return array_of(self.merge(ea, eb, line, what))
        raise KiteError("%s：一个是%s，一个是%s，对不上"
                        % (what, type_cn(a), type_cn(b)), line)

    # -- 表达式类型

    def type_of(self, n):
        t = type(n)

        if t is Num:
            return NUM
        if t is Text:
            return STR
        if t is Interp:
            for part in n.parts:
                self.expect_type(self.type_of(part), _PRINTABLE, n.line, "插值")
            return STR
        if t is Name:
            return self.lookup(n.id, n.line)
        if t is ListLit:
            if not n.items:
                raise KiteError("空数组不支持，至少写一个元素", n.line)
            elem = UNK
            for item in n.items:
                it = self.type_of(item)
                if it in self.record_array_types:
                    raise KiteError("记录数组不支持二维", item.line)
                self.expect_type(it, (*_SCALAR, *_ARRAY, *self.records), item.line, "数组元素")
                elem = self.merge(elem, it, n.line, "数组元素")
            if elem == UNK:
                return UNK
            if elem in _ARRAY:
                if any(not isinstance(row, ListLit) for row in n.items):
                    raise KiteError("二维数组的每一行都要写成 [ ... ]", n.line)
                if any(len(row.items) != len(n.items[0].items) for row in n.items):
                    raise KiteError("二维数组每行的长度要一样", n.line)
            return array_of(elem)

        if t is Unary:
            self.number(n.operand, "%s 的操作数" % n.op)
            return NUM

        if t is BinOp:
            if n.op == "..":
                raise KiteError("1..5 这种范围只能写在 rp 后面或切片里", n.line)
            lt = self.type_of(n.left)
            rt = self.type_of(n.right)
            if n.op == "+":
                for operand_type in (lt, rt):
                    self.expect_type(operand_type, _SCALAR, n.line, "+ 的操作数")
                if STR in (lt, rt):
                    return STR
                # 一个尚未推断的操作数仍可能是文本，不能先定成数字。
                return UNK if UNK in (lt, rt) else NUM
            if n.op in ("==", "!=", "<", ">", "<=", ">="):
                for operand_type in (lt, rt):
                    self.expect_type(operand_type, _SCALAR, n.line, "比较的操作数")
                self.merge(lt, rt, n.line, "比较的操作数")
                return NUM
            for operand_type in (lt, rt):
                self.expect_type(operand_type, NUM, n.line, "%s 的操作数" % n.op)
            return NUM

        if t is Field:
            target_type = self.type_of(n.target)
            if target_type == UNK:
                return UNK
            if target_type in self.records:
                fields = dict(self.records[target_type].fields)
                if n.name in fields:
                    n.owner = target_type
                    return fields[n.name]
                if (n.fallback or n.name) not in self.funcs and n.name not in BUILTINS:
                    raise KiteError("记录没有字段「%s」" % n.name, n.line)
            n.owner = None
            return self.call_type(Call(Name(n.fallback or n.name, n.line), [n.target], n.line))

        if t is Slice:
            base = self.type_of(n.target)
            self.number(n.from_, "切片起点")
            self.number(n.to, "切片终点")
            if base == STR:
                return STR
            if base == UNK:
                return UNK
            if is_matrix(base):
                raise KiteError("还不能切二维表", n.line)
            if elem_of(base) is not None:
                return base
            raise KiteError("切片只能用在文本或一维数组上", n.line)

        if t is Index:
            base = self.type_of(n.target)
            self.number(n.index, "数组下标")
            if base == UNK:
                return UNK
            e = elem_of(base)
            if e is None:
                raise KiteError("只有数组才能用 [] 取元素", n.line)
            return e

        if t is Call:
            return self.call_type(n)

        raise KiteError("内部错误：不认识的表达式", getattr(n, "line", 0))

    def call_type(self, n):
        if not isinstance(n.callee, Name):
            raise KiteError("只能调用有名字的函数", n.line)
        name = n.callee.id

        if name in BUILTINS or name in self.extra:
            return self.builtin_type(name, n)

        if name in self.records:
            fields = self.records[name].fields
            if len(n.args) != len(fields):
                raise KiteError("记录构造需要 %d 个参数，这里给了 %d 个" % (len(fields), len(n.args)), n.line)
            for arg, (field, annotation) in zip(n.args, fields):
                self.expect_type(self.type_of(arg), annotation, arg.line, "字段「%s」" % field)
            return name

        if name not in self.funcs:
            raise KiteError("没有叫「%s」的函数" % name, n.line)

        fn = self.funcs[name]
        if len(n.args) != len(fn.params):
            raise KiteError("%s 需要 %d 个参数，这里给了 %d 个"
                            % (name, len(fn.params), len(n.args)), n.line)

        for i, arg in enumerate(n.args):
            at = self.type_of(arg)
            self.expect_type(at, self.value_types, arg.line, "函数参数")
            merged = self.merge(self.ptypes[name][i], at, n.line,
                                "%s 的第 %d 个参数" % (name, i + 1))
            if merged != self.ptypes[name][i]:
                self.ptypes[name][i] = merged
                self.changed = True

        return self.rtypes[name]

    def builtin_type(self, name, node):
        signatures = _BUILTIN_PARAMS.get(name)
        if name in self.extra:
            signatures = _UNITY_PARAMS.get(name, signatures)
        if self.record_array_types:
            if name == "len":
                signatures += ((self.record_array_types,),)
            elif name == "push":
                signatures += tuple(zip(self.record_array_types, self.records))
        if signatures is None:
            raise KiteError("缺少内置函数 %s 的参数签名" % name, node.line)
        arities = sorted({len(sig) for sig in signatures})
        candidates = [sig for sig in signatures if len(sig) == len(node.args)]
        if not candidates:
            raise KiteError("%s 需要 %s 个参数，这里给了 %d 个"
                            % (name, " 或 ".join(map(str, arities)), len(node.args)), node.line)

        types = []
        for i, arg in enumerate(node.args):
            if name == "serve" and i == 1:
                if not isinstance(arg, Name) or arg.id not in self.funcs:
                    raise KiteError("serve 的第二个参数要写一个函数名", arg.line)
                if self.ptypes[arg.id]:
                    raise KiteError("serve 用的函数不能带参数", arg.line)
                self.expect_type(self.rtypes[arg.id], STR, arg.line, "serve 处理函数的返回值")
                types.append("处理函数")
            else:
                types.append(self.type_of(arg))

        if name == "push":
            target = node.args[0]
            if not isinstance(target, Name):
                raise KiteError("push 要作用在一维数组变量上，比如 xs.push(3)", node.line)
            if self.is_borrowed(target.id):
                raise KiteError("不能对函数参数或矩阵行 push", node.line)

        for i, actual in enumerate(types):
            if actual == UNK:
                continue
            options = tuple(dict.fromkeys(
                ty for sig in candidates
                for ty in (sig[i] if isinstance(sig[i], tuple) else (sig[i],))
            ))
            self.expect_type(actual, options, node.args[i].line,
                             "%s 的第 %d 个参数" % (name, i + 1))
            candidates = [sig for sig in candidates
                          if actual == sig[i] or (isinstance(sig[i], tuple) and actual in sig[i])]

        if name == "mat":
            return UNK if types[2] == UNK else array_of(array_of(types[2]))
        if name in self.extra:
            return self.extra[name]
        return BUILTIN_TYPES[name]

    # -- 语句

    @staticmethod
    def is_fresh_array(expr):
        return (isinstance(expr, (ListLit, Slice))
                or isinstance(expr, Call) and isinstance(expr.callee, Name)
                and expr.callee.id in ("mat", "split"))

    def walk_block(self, block):
        self.push()
        for stmt in block.stmts:
            self.walk_stmt(stmt)
        self.pop()

    def walk_stmt(self, n):
        t = type(n)

        if t is ExprStmt:
            self.type_of(n.expr)
            return

        if t is Assign:
            vt = self.type_of(n.value)
            self.expect_type(vt, self.value_types, n.value.line, "赋值右边")
            if isinstance(n.target, Name):
                name = n.target.id
                for scope in reversed(self.scopes):
                    if name in scope:
                        if elem_of(scope[name]) is not None:
                            raise KiteError("数组不能整个重新赋值（用 xs[1] = ... 一个个改）", n.line)
                        scope[name] = self.merge(scope[name], vt, n.line, "「%s」" % name)
                        break
                else:
                    if elem_of(vt) is not None and not self.is_fresh_array(n.value):
                        raise KiteError("数组变量只能用新建数组初始化，例如数组字面量或切片", n.line)
                    self.declare(name, vt, n.line)
                return
            if isinstance(n.target, Index):
                et = self.type_of(n.target)
                if elem_of(et) is not None:
                    raise KiteError("不能整行赋值，用 m[i][j] = ... 一个个改", n.line)
                self.expect_type(vt, (*_SCALAR, *self.records), n.value.line, "数组元素")
                self.merge(et, vt, n.line, "数组元素")
                return

        if t is Say:
            for e in n.exprs:
                et = self.type_of(e)
                if et == VOID:
                    raise KiteError("这个表达式没有值，不能打印", n.line)
                self.expect_type(et, _PRINTABLE, e.line, "打印值")
            return

        if t is If:
            for cond, body in n.branches:
                self.number(cond, "if/elif 条件")
                self.walk_block(body)
            if n.orelse is not None:
                self.walk_block(n.orelse)
            return

        if t is Loop:
            self.walk_loop(n)
            return

        if t is Return:
            if self.cur is None:
                raise KiteError("ret 只能写在函数里", n.line)
            if n.expr is None:
                if self.rtypes[self.cur] != VOID:
                    raise KiteError("这个函数需要返回值，ret 后面不能空着", n.line)
                return
            rt = self.type_of(n.expr)
            if elem_of(rt) is not None:
                raise KiteError("函数不能返回数组", n.line)
            self.expect_type(rt, self.return_types, n.line, "返回值")
            merged = self.merge(self.rtypes[self.cur], rt, n.line, "返回值")
            if merged != self.rtypes[self.cur]:
                self.rtypes[self.cur] = merged
                self.changed = True
            return

        if t is Break or t is Continue:
            if self.loop_depth == 0:
                raise KiteError("%s 只能写在循环里" % ("break" if t is Break else "continue"), n.line)
            return

        if t in (FnDef, RecordDef, ExternDef):
            raise KiteError("fn、record 和 extern 只能定义在程序顶层", n.line)

        raise KiteError("内部错误：不认识的语句", getattr(n, "line", 0))

    def walk_loop(self, node):
        name = None
        var_type = NUM
        if node.mode == "until":
            self.number(node.source, "ut 条件")
        else:
            name = node.name or "count"
            source = node.source
            if isinstance(source, BinOp) and source.op == "..":
                self.number(source.left, "范围起点")
                self.number(source.right, "范围终点")
            else:
                source_type = self.type_of(source)
                if source_type in (NUM, UNK):
                    var_type = source_type
                else:
                    var_type = elem_of(source_type)
                    if var_type is None:
                        raise KiteError("rp 后面要么是次数、1..5、或者一个数组", node.line)

        self.push()
        self.loop_depth += 1
        if name is not None:
            self.declare(name, var_type, node.line)
            if elem_of(var_type) is not None:
                self.borrowed[-1].add(name)
        for stmt in node.body.stmts:
            self.walk_stmt(stmt)
        self.loop_depth -= 1
        self.pop()

    def walk_fn(self, fn):
        self.reset_scope(fn.name)
        for (pname, _), ty in zip(fn.params, self.ptypes[fn.name]):
            if pname in self.scopes[-1]:
                raise KiteError("函数 %s 的参数「%s」重复了" % (fn.name, pname), fn.line)
            self.declare(pname, ty, fn.line)
            self.borrowed[-1].add(pname)
        for stmt in fn.body.stmts:
            self.walk_stmt(stmt)

    @staticmethod
    def check_at(node, check):
        try:
            check(node)
        except KiteError as error:
            if not error.path:
                error.path = getattr(node, "source_path", None)
            raise

    def run(self):
        while True:
            self.changed = False
            self.reset_scope()
            for s in self.program.stmts:
                if not isinstance(s, (FnDef, RecordDef, ExternDef)):
                    self.check_at(s, self.walk_stmt)
            for fn in self.funcs.values():
                if isinstance(fn, FnDef):
                    self.check_at(fn, self.walk_fn)
            if not self.changed:
                break

        for name, fn in self.funcs.items():
            if isinstance(fn, ExternDef):
                continue
            path = getattr(fn, "source_path", None)
            display_name = name.rsplit("::", 1)[-1]
            if self.rtypes[name] != VOID and not self.block_returns(fn.body):
                raise KiteError("函数 %s 有路径没有返回值，请补上 ret" % display_name, fn.line, path)
            for i, (pname, _) in enumerate(fn.params):
                if self.ptypes[name][i] == UNK:
                    param = pname.rsplit("::", 1)[-1]
                    raise KiteError(
                        "推不出函数 %s 的参数「%s」是什么类型。"
                        "写一次调用它，或者写成「%s: number」" % (display_name, param, param),
                        fn.line, path)
            if self.rtypes[name] == UNK:
                raise KiteError(
                    "推不出函数 %s 返回什么。给它加个标注「-> number」" % display_name,
                    fn.line, path)

        return self.ptypes, self.rtypes


# ============================================================ 内置函数

BUILTINS = {
    "len", "txt", "num", "up", "low", "trim", "read", "write",
    "sum", "avg", "max", "min", "sort", "join", "split", "times", "has",
    "ask", "rand", "seed", "mat",
    "abs", "floor", "round", "sqrt", "pow",
    "rep", "find", "sub", "repl",
    "now", "date", "ts", "exist", "del", "hex", "bin",
    "serve", "form", "push", "html",
}

BUILTIN_TYPES = {
    "len": NUM,
    "txt": STR,
    "num": NUM,
    "up": STR,
    "low": STR,
    "trim": STR,
    "read": STR,
    "write": VOID,
    "sum": NUM,
    "avg": NUM,
    "max": NUM,
    "min": NUM,
    "sort": VOID,
    "join": STR,
    "split": STR + "[]",
    "times": NUM,
    "has": NUM,
    "ask": STR,
    "rand": NUM,
    "seed": VOID,
    "mat": NUM + "[][]",
    "abs": NUM, "floor": NUM, "round": NUM, "sqrt": NUM, "pow": NUM,
    "rep": STR, "find": NUM, "sub": STR, "repl": STR,
    "now": STR, "date": STR, "ts": NUM, "exist": NUM, "del": VOID,
    "hex": STR, "bin": STR,
    "serve": VOID, "form": STR, "push": VOID, "html": STR,
}


# ============================================================ 运行时

RUNTIME = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <math.h>
#include <limits.h>
#include <time.h>
#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <signal.h>
#include <sys/time.h>
#endif

/* 数组：带长度的结构体，这样才能从函数返回、才能 join */
typedef struct { double *v; int n; int cap; } NumArr;
typedef struct { const char **v; int n; int cap; } StrArr;
typedef struct { double *v; int rows; int cols; } NumMat;
typedef struct { const char **v; int rows; int cols; } StrMat;

static void rt_fail(const char *msg, int line);

static NumArr rt_make_num(int n, const double *src) {
    NumArr a;
    a.v = (double *)malloc(sizeof(double) * (size_t)(n > 0 ? n : 1));
    memcpy(a.v, src, sizeof(double) * (size_t)n);
    a.n = n;
    a.cap = n;
    return a;
}
static StrArr rt_make_str(int n, const char **src) {
    StrArr a;
    a.v = (const char **)malloc(sizeof(char *) * (size_t)(n > 0 ? n : 1));
    memcpy((void *)a.v, src, sizeof(char *) * (size_t)n);
    a.n = n;
    a.cap = n;
    return a;
}

/* ---- 打印数组 ---- */
static char *rt_join_num(NumArr a, const char *sep);
static char *rt_join_str(StrArr a, const char *sep);
static char *rt_show_num(NumArr a) {
    char *inner = rt_join_num(a, ", ");
    size_t n = strlen(inner) + 3;
    char *out = (char *)malloc(n);
    snprintf(out, n, "[%s]", inner);
    free(inner);
    return out;
}
static char *rt_show_str(StrArr a) {
    size_t total = 3;
    for (int i = 0; i < a.n; i++) total += strlen(a.v[i]) * 6 + 4;
    char *out = (char *)malloc(total);
    char *p = out;
    *p++ = '[';
    for (int i = 0; i < a.n; i++) {
        if (i) { *p++ = ','; *p++ = ' '; }
        *p++ = '"';
        for (const unsigned char *c = (const unsigned char *)a.v[i]; *c; c++) {
            const char *escape = NULL;
            switch (*c) {
                case '\\': escape = "\\\\"; break;
                case '"':  escape = "\\\""; break;
                case '\n': escape = "\\n"; break;
                case '\r': escape = "\\r"; break;
                case '\t': escape = "\\t"; break;
                case '\b': escape = "\\b"; break;
                case '\f': escape = "\\f"; break;
            }
            if (escape) { *p++ = escape[0]; *p++ = escape[1]; }
            else if (*c < 32) { snprintf(p, 7, "\\u%04x", (unsigned)*c); p += 6; }
            else *p++ = (char)*c;
        }
        *p++ = '"';
    }
    *p++ = ']';
    *p = 0;
    return out;
}

/* ---- 读键盘 ---- */
static char *rt_ask(const char *prompt) {
    if (prompt && *prompt) {
        fputs(prompt, stdout);
        fflush(stdout);
    }
    size_t cap = 128, len = 0;
    char *buf = (char *)malloc(cap);
    int c;
    for (;;) {
        c = fgetc(stdin);
        if (c == EOF || c == '\n') break;
        if (c == '\r') {
            int d = fgetc(stdin);
            if (d != '\n' && d != EOF) ungetc(d, stdin);
            break;
        }
        if (len + 2 > cap) {
            cap *= 2;
            buf = (char *)realloc(buf, cap);
        }
        buf[len++] = (char)c;
    }
    buf[len] = 0;
    return buf;
}

/* ---- 随机数：自己实现，换机器结果也一样 ---- */
static unsigned long long rt_rng = 0;
static void rt_seed(double s) {
    rt_rng = (unsigned long long)(long long)s * 6364136223846793005ULL
             + 1442695040888963407ULL;
    if (!rt_rng) rt_rng = 88172645463325252ULL;
}
static unsigned long long rt_next_random(void) {
    unsigned long long x = rt_rng;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    rt_rng = x;
    return x;
}
static double rt_rand(double n) {
    if (!rt_rng) {
        rt_seed((double)time(NULL));
        rt_next_random();
    }
    unsigned long long x = rt_next_random();
    long long limit = (long long)n;
    if (limit <= 0) return 0;
    return (double)(x % (unsigned long long)limit);
}

static int rt_index(double i, int n, int line) {
    double k = trunc(i);
    if (!isfinite(k)) rt_fail("下标要是有限数字", line);
    if (k == 0) rt_fail("下标从 1 开始数，没有第 0 个", line);
    if (k < 0) k = n + k + 1;
    if (k < 1 || k > n) {
        fprintf(stderr, "出错了：第 %d 行：越界（下标 %g，长度 %d，从 1 开始数）\n",
                line, i, n);
        exit(1);
    }
    return (int)k - 1;
}
static double rt_get_num(NumArr a, double i, int line) {
    return a.v[rt_index(i, a.n, line)];
}
static const char *rt_get_str(StrArr a, double i, int line) {
    return a.v[rt_index(i, a.n, line)];
}
static void rt_set_num(NumArr a, double i, double v, int line) {
    a.v[rt_index(i, a.n, line)] = v;
}
static void rt_set_str(StrArr a, double i, const char *v, int line) {
    a.v[rt_index(i, a.n, line)] = v;
}
static void rt_push_num(NumArr *a, double v, int line) {
    if (a->cap < 0) rt_fail("这一行是表中的一行，不能 push", line);
    if (a->n >= a->cap) {
        int nc = a->cap > 0 ? a->cap * 2 : 4;
        a->v = (double *)realloc(a->v, sizeof(double) * (size_t)nc);
        a->cap = nc;
    }
    a->v[a->n++] = v;
}
static void rt_push_str(StrArr *a, const char *v, int line) {
    if (a->cap < 0) rt_fail("这一行是表中的一行，不能 push", line);
    if (a->n >= a->cap) {
        int nc = a->cap > 0 ? a->cap * 2 : 4;
        a->v = (const char **)realloc((void *)a->v, sizeof(char *) * (size_t)nc);
        a->cap = nc;
    }
    a->v[a->n++] = v;
}
static double rt_slice_position(double i, int n, int line) {
    if (!isfinite(i)) rt_fail("切片下标要是有限数字", line);
    double k = trunc(i);
    return k < 0 ? n + k + 1 : k;
}
static int rt_slice_start(double i, int n, int line) {
    return (int)fmin((double)n + 1, fmax(1, rt_slice_position(i, n, line)));
}
static int rt_slice_end(double i, int n, int line) {
    return (int)fmin(n, fmax(0, rt_slice_position(i, n, line)));
}
/* Each record gets a typed array with a shared implementation. */
#define KITE_RECORD_ARRAY(T, A) \
    typedef struct { T *v; int n; int cap; } A; \
    static A A##_make(int n, const T *src, int line) { \
        A a = {NULL, n, n}; \
        if (n > 0) { \
            if ((size_t)n > (size_t)-1 / sizeof(T)) rt_fail("数组太大", line); \
            a.v = (T *)malloc((size_t)n * sizeof(T)); \
            if (!a.v) rt_fail("无法分配数组内存", line); \
            memcpy(a.v, src, (size_t)n * sizeof(T)); \
        } \
        return a; \
    } \
    static T A##_get(A a, double i, int line) { \
        return a.v[rt_index(i, a.n, line)]; \
    } \
    static void A##_set(A a, double i, T item, int line) { \
        a.v[rt_index(i, a.n, line)] = item; \
    } \
    static void A##_push(A *a, T item, int line) { \
        if (a->n == a->cap) { \
            if (a->cap >= INT_MAX - 1) rt_fail("数组太大", line); \
            int cap = a->cap == 0 ? 4 : a->cap <= (INT_MAX - 1) / 2 ? a->cap * 2 : INT_MAX - 1; \
            if ((size_t)cap > (size_t)-1 / sizeof(T)) rt_fail("数组太大", line); \
            T *items = (T *)realloc(a->v, (size_t)cap * sizeof(T)); \
            if (!items) rt_fail("无法分配数组内存", line); \
            a->v = items; \
            a->cap = cap; \
        } \
        a->v[a->n++] = item; \
    } \
    static A A##_slice(A a, double f, double t, int line) { \
        int from = rt_slice_start(f, a.n, line); \
        int to = rt_slice_end(t, a.n, line); \
        return from > to ? A##_make(0, NULL, line) : A##_make(to - from + 1, a.v + (from - 1), line); \
    }

static NumArr rt_slice_num(NumArr a, double f, double t, int line) {
    int from = rt_slice_start(f, a.n, line);
    int to = rt_slice_end(t, a.n, line);
    NumArr r;
    if (from > to) {
        r.v = (double *)malloc(sizeof(double));
        r.n = 0;
        r.cap = 0;
        return r;
    }
    int m = to - from + 1;
    double *v = (double *)malloc(sizeof(double) * (size_t)m);
    memcpy(v, a.v + from - 1, sizeof(double) * (size_t)m);
    r.v = v;
    r.n = m;
    r.cap = m;
    return r;
}
static StrArr rt_slice_arr(StrArr a, double f, double t, int line) {
    int from = rt_slice_start(f, a.n, line);
    int to = rt_slice_end(t, a.n, line);
    StrArr r;
    if (from > to) {
        r.v = (const char **)malloc(sizeof(char *));
        r.n = 0;
        r.cap = 0;
        return r;
    }
    int m = to - from + 1;
    const char **v = (const char **)malloc(sizeof(char *) * (size_t)m);
    memcpy(v, a.v + from - 1, sizeof(char *) * (size_t)m);
    r.v = v;
    r.n = m;
    r.cap = m;
    return r;
}
/* Text positions count UTF-8 code points. Source text is UTF-8. */
static const char *rt_utf8_next(const char *s) {
    if (*s) {
        do { s++; } while (((unsigned char)*s & 0xc0) == 0x80);
    }
    return s;
}
static int rt_text_len(const char *s) {
    int count = 0;
    for (; *s; s = rt_utf8_next(s)) count++;
    return count;
}
static const char *rt_text_at(const char *s, int count) {
    while (count-- > 0 && *s) s = rt_utf8_next(s);
    return s;
}
static char *rt_copy_text(const char *start, const char *end) {
    size_t bytes = (size_t)(end - start);
    char *out = (char *)malloc(bytes + 1);
    memcpy(out, start, bytes);
    out[bytes] = 0;
    return out;
}
static char *rt_slice_str(const char *s, double f, double t, int line) {
    int n = rt_text_len(s);
    int from = rt_slice_start(f, n, line);
    int to = rt_slice_end(t, n, line);
    if (from > to) return strdup("");
    return rt_copy_text(rt_text_at(s, from - 1), rt_text_at(s, to));
}
static char *rt_cat(const char *a, const char *b) {
    size_t la = strlen(a), lb = strlen(b);
    char *r = (char *)malloc(la + lb + 1);
    memcpy(r, a, la);
    memcpy(r + la, b, lb + 1);
    return r;
}
static void rt_format_num(char r[64], double v) {
    if (isnan(v)) { strcpy(r, "nan"); return; }
    if (isinf(v)) { strcpy(r, v < 0 ? "-inf" : "inf"); return; }
    snprintf(r, 64, "%.15g", v == 0 ? 0.0 : v);
    char *e = strchr(r, 'e');
    if (e) {
        int exponent = atoi(e + 1);
        snprintf(e + 1, 12, "%d", exponent);
    }
}
static char *rt_str_num(double v) {
    char r[64];
    rt_format_num(r, v);
    return strdup(r);
}
static int rt_ascii_space(char c) {
    return c == ' ' || (c >= '\t' && c <= '\r');
}
static int rt_digit(char c) { return c >= '0' && c <= '9'; }
static double rt_num(const char *s, int line) {
    while (rt_ascii_space(*s)) s++;
    if (!*s) return 0;
    const char *p = s;
    if (*p == '+' || *p == '-') p++;
    const char *digits = p;
    while (rt_digit(*p)) p++;
    int has_digit = p != digits;
    if (*p == '.') {
        digits = ++p;
        while (rt_digit(*p)) p++;
        has_digit |= p != digits;
    }
    if (!has_digit) rt_fail("不能转成数字", line);
    if (*p == 'e' || *p == 'E') {
        p++;
        if (*p == '+' || *p == '-') p++;
        if (!rt_digit(*p)) rt_fail("不能转成数字", line);
        while (rt_digit(*p)) p++;
    }
    while (rt_ascii_space(*p)) p++;
    double result = strtod(s, NULL);
    if (*p || !isfinite(result)) rt_fail("不能转成数字", line);
    return result;
}
static char *rt_upper(const char *s) {
    char *r = strdup(s);
    for (char *p = r; *p; p++) *p = (char)toupper((unsigned char)*p);
    return r;
}
static char *rt_lower(const char *s) {
    char *r = strdup(s);
    for (char *p = r; *p; p++) *p = (char)tolower((unsigned char)*p);
    return r;
}
static char *rt_trim(const char *s) {
    while (*s && isspace((unsigned char)*s)) s++;
    size_t n = strlen(s);
    while (n > 0 && isspace((unsigned char)s[n - 1])) n--;
    char *r = (char *)malloc(n + 1);
    memcpy(r, s, n);
    r[n] = 0;
    return r;
}
static char *rt_read(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return strdup("");
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n < 0) { fclose(f); return strdup(""); }
    char *buf = (char *)malloc((size_t)n + 1);
    size_t got = fread(buf, 1, (size_t)n, f);
    buf[got] = 0;
    fclose(f);
    return buf;
}
static void rt_write(const char *path, const char *s) {
    FILE *f = fopen(path, "wb");
    if (!f) return;
    fputs(s, f);
    fclose(f);
}

/* ---- 常用算法 ---- */
static double rt_sum(NumArr a) {
    double s = 0;
    for (int i = 0; i < a.n; i++) s += a.v[i];
    return s;
}
static double rt_avg(NumArr a) {
    return a.n ? rt_sum(a) / a.n : 0;
}
static double rt_max(NumArr a) {
    double m = a.n ? a.v[0] : 0;
    for (int i = 1; i < a.n; i++) if (a.v[i] > m) m = a.v[i];
    return m;
}
static double rt_min(NumArr a) {
    double m = a.n ? a.v[0] : 0;
    for (int i = 1; i < a.n; i++) if (a.v[i] < m) m = a.v[i];
    return m;
}
static int rt_cmp_num(const void *x, const void *y) {
    double a = *(const double *)x, b = *(const double *)y;
    return (a > b) - (a < b);
}
static int rt_cmp_str(const void *x, const void *y) {
    const char *a = *(const char * const *)x;
    const char *b = *(const char * const *)y;
    return strcmp(a, b);
}
static void rt_sort_num(NumArr a) {
    qsort(a.v, (size_t)a.n, sizeof(double), rt_cmp_num);
}
static void rt_sort_str(StrArr a) {
    qsort(a.v, (size_t)a.n, sizeof(char *), rt_cmp_str);
}
static char *rt_join_num(NumArr a, const char *sep) {
    size_t total = 1, sl = strlen(sep);
    char **parts = (char **)malloc(sizeof(char *) * (size_t)(a.n > 0 ? a.n : 1));
    for (int i = 0; i < a.n; i++) {
        parts[i] = rt_str_num(a.v[i]);
        total += strlen(parts[i]) + sl;
    }
    char *out = (char *)malloc(total + 1);
    out[0] = 0;
    for (int i = 0; i < a.n; i++) {
        if (i) strcat(out, sep);
        strcat(out, parts[i]);
        free(parts[i]);
    }
    free(parts);
    return out;
}
static char *rt_join_str(StrArr a, const char *sep) {
    size_t total = 1, sl = strlen(sep);
    for (int i = 0; i < a.n; i++) total += strlen(a.v[i]) + sl;
    char *out = (char *)malloc(total + 1);
    out[0] = 0;
    for (int i = 0; i < a.n; i++) {
        if (i) strcat(out, sep);
        strcat(out, a.v[i]);
    }
    return out;
}
static double rt_count_num(NumArr a, double v) {
    double c = 0;
    for (int i = 0; i < a.n; i++) if (a.v[i] == v) c += 1;
    return c;
}
static double rt_count_str(StrArr a, const char *v) {
    double c = 0;
    for (int i = 0; i < a.n; i++) if (strcmp(a.v[i], v) == 0) c += 1;
    return c;
}
static double rt_contains_num(NumArr a, double v) {
    for (int i = 0; i < a.n; i++) if (a.v[i] == v) return 1;
    return 0;
}
static double rt_contains_str(StrArr a, const char *v) {
    for (int i = 0; i < a.n; i++) if (strcmp(a.v[i], v) == 0) return 1;
    return 0;
}
static StrArr rt_split(const char *s, const char *sep) {
    StrArr r;
    r.v = NULL;
    r.n = 0;
    size_t sl = strlen(sep);
    if (sl == 0) {
        r.v = (const char **)malloc(sizeof(char *));
        r.v[0] = strdup(s);
        r.n = 1;
        r.cap = 1;
        return r;
    }
    int cap = 0;
    const char *p = s;
    for (;;) {
        const char *q = strstr(p, sep);
        size_t len = q ? (size_t)(q - p) : strlen(p);
        if (r.n == cap) {
            cap = cap ? cap * 2 : 4;
            r.v = (const char **)realloc((void *)r.v, sizeof(char *) * (size_t)cap);
        }
        char *piece = (char *)malloc(len + 1);
        memcpy(piece, p, len);
        piece[len] = 0;
        r.v[r.n++] = piece;
        if (!q) break;
        p = q + sl;
    }
    r.cap = cap;
    return r;
}
static NumArr rt_row_num(NumMat m, double i, int line) {
    int k = rt_index(i, m.rows, line);
    NumArr row;
    row.v = m.v + (size_t)k * (size_t)m.cols;
    row.n = m.cols;
    row.cap = -1;
    return row;
}
static StrArr rt_row_str(StrMat m, double i, int line) {
    int k = rt_index(i, m.rows, line);
    StrArr row;
    row.v = m.v + (size_t)k * (size_t)m.cols;
    row.n = m.cols;
    row.cap = -1;
    return row;
}
static NumMat rt_matrix_num(double r, double c, double fill, int line) {
    r = trunc(r);
    c = trunc(c);
    if (!isfinite(r) || !isfinite(c) || r < 1 || c < 1 || r * c > 10000000)
        rt_fail("mat 的尺寸不合理", line);
    int rr = (int)r, cc = (int)c;
    double *data = (double *)malloc(sizeof(double) * (size_t)(rr * cc));
    for (long long i = 0; i < rr * cc; i++) data[i] = fill;
    NumMat m;
    m.v = data;
    m.rows = (int)rr;
    m.cols = (int)cc;
    return m;
}
static StrMat rt_matrix_str(double r, double c, const char *fill, int line) {
    r = trunc(r);
    c = trunc(c);
    if (!isfinite(r) || !isfinite(c) || r < 1 || c < 1 || r * c > 10000000)
        rt_fail("mat 的尺寸不合理", line);
    int rr = (int)r, cc = (int)c;
    const char **data = (const char **)malloc(sizeof(char *) * (size_t)(rr * cc));
    for (long long i = 0; i < rr * cc; i++) data[i] = fill;
    StrMat m;
    m.v = data;
    m.rows = (int)rr;
    m.cols = (int)cc;
    return m;
}
static char *rt_show_mat_num(NumMat m) {
    size_t total = 3;
    char **rows = (char **)malloc(sizeof(char *) * (size_t)(m.rows > 0 ? m.rows : 1));
    for (int i = 0; i < m.rows; i++) {
        NumArr r;
        r.v = m.v + (size_t)i * (size_t)m.cols;
        r.n = m.cols;
        rows[i] = rt_join_num(r, ", ");
        total += strlen(rows[i]) + 4;
    }
    char *out = (char *)malloc(total + 1);
    char *p = out;
    *p++ = '[';
    for (int i = 0; i < m.rows; i++) {
        if (i) { *p++ = ','; *p++ = ' '; }
        *p++ = '[';
        size_t l = strlen(rows[i]);
        memcpy(p, rows[i], l);
        p += l;
        *p++ = ']';
        free(rows[i]);
    }
    *p++ = ']';
    *p = 0;
    free(rows);
    return out;
}
static char *rt_show_mat_str(StrMat m) {
    size_t total = 3;
    char **rows = (char **)malloc(sizeof(char *) * (size_t)(m.rows > 0 ? m.rows : 1));
    for (int i = 0; i < m.rows; i++) {
        StrArr r;
        r.v = m.v + (size_t)i * (size_t)m.cols;
        r.n = m.cols;
        rows[i] = rt_show_str(r);
        total += strlen(rows[i]) + 2;
    }
    char *out = (char *)malloc(total + 1);
    char *p = out;
    *p++ = '[';
    for (int i = 0; i < m.rows; i++) {
        if (i) { *p++ = ','; *p++ = ' '; }
        size_t l = strlen(rows[i]);
        memcpy(p, rows[i], l);
        p += l;
        free(rows[i]);
    }
    *p++ = ']';
    *p = 0;
    free(rows);
    return out;
}
static void rt_fail(const char *msg, int line) {
    fprintf(stderr, "出错了：第 %d 行：%s\n", line, msg);
    exit(1);
}
static double rt_step(double value, double step) {
    double next = value + step;
    return next == value ? NAN : next;
}
static double rt_abs(double x) { return fabs(x); }
static double rt_floor(double x) { return floor(x); }
static double rt_round(double x) { return floor(x + 0.5); }
static double rt_sqrt(double x, int line) {
    if (x < 0) rt_fail("sqrt 不能对负数开方", line);
    return sqrt(x);
}
static char *rt_rep(const char *s, double n, int line) {
    long k = (long)n;
    if (k <= 0) return strdup("");
    size_t l = strlen(s);
    if (l > 0 && (size_t)k > 50000000 / l) rt_fail("rep 重复得太多了", line);
    size_t total = l * (size_t)k;
    char *out = (char *)malloc(total + 1);
    for (long i = 0; i < k; i++) memcpy(out + (size_t)i * l, s, l);
    out[total] = 0;
    return out;
}
static double rt_find(const char *s, const char *t) {
    const char *p = strstr(s, t);
    if (!p) return -1;
    int count = 0;
    for (; s < p; s = rt_utf8_next(s)) count++;
    return count;
}
static char *rt_sub(const char *s, double start, double len, int line) {
    (void)line;
    int n = rt_text_len(s);
    int st = (int)fmin(n, fmax(0, start));
    int ln = (int)fmin(n - st, fmax(0, len));
    return rt_copy_text(rt_text_at(s, st), rt_text_at(s, st + ln));
}
static char *rt_repl(const char *s, const char *from, const char *to) {
    size_t fl = strlen(from);
    if (fl == 0) return strdup(s);
    size_t count = 0;
    const char *p = s;
    while ((p = strstr(p, from)) != NULL) { count++; p += fl; }
    size_t tl = strlen(to);
    size_t total = strlen(s) - count * fl + count * tl;
    char *out = (char *)malloc(total + 1);
    char *w = out;
    p = s;
    for (;;) {
        const char *q = strstr(p, from);
        if (!q) { strcpy(w, p); break; }
        size_t head = (size_t)(q - p);
        memcpy(w, p, head);
        w += head;
        memcpy(w, to, tl);
        w += tl;
        p = q + fl;
    }
    return out;
}
static double rt_ts(void) { return (double)time(NULL); }
static char *rt_now(void) {
    char buf[32];
    time_t t = time(NULL);
    struct tm *lt = localtime(&t);
    strftime(buf, sizeof buf, "%Y-%m-%d %H:%M:%S", lt);
    return strdup(buf);
}
static char *rt_date(void) {
    char buf[16];
    time_t t = time(NULL);
    struct tm *lt = localtime(&t);
    strftime(buf, sizeof buf, "%Y-%m-%d", lt);
    return strdup(buf);
}
static double rt_exist(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    fclose(f);
    return 1;
}
static void rt_del(const char *path) { remove(path); }
static char *rt_hex(double v) {
    char buf[32];
    long long n = (long long)v;
    if (n < 0) snprintf(buf, sizeof buf, "-%llx", (unsigned long long)(-n));
    else snprintf(buf, sizeof buf, "%llx", (unsigned long long)n);
    return strdup(buf);
}
static char *rt_html(const char *s) {
    char *out = (char *)malloc(strlen(s) * 6 + 1);
    char *p = out;
    for (; *s; s++) {
        const char *entity = NULL;
        switch (*s) {
            case '&':  entity = "&amp;"; break;
            case '<':  entity = "&lt;"; break;
            case '>':  entity = "&gt;"; break;
            case '"':  entity = "&quot;"; break;
            case '\'': entity = "&#39;"; break;
        }
        if (entity) {
            size_t n = strlen(entity);
            memcpy(p, entity, n);
            p += n;
        } else *p++ = *s;
    }
    *p = 0;
    return out;
}
static char *rt_url_decode(const char *s, size_t n) {
    char *out = (char *)malloc(n + 1);
    size_t j = 0;
    for (size_t i = 0; i < n; i++) {
        if (s[i] == '%' && i + 2 < n
            && isxdigit((unsigned char)s[i + 1])
            && isxdigit((unsigned char)s[i + 2])) {
            char hex[3] = {s[i + 1], s[i + 2], 0};
            long byte = strtol(hex, NULL, 16);
            if (byte == 0) { free(out); return strdup(""); }
            out[j++] = (char)byte;
            i += 2;
        } else out[j++] = s[i] == '+' ? ' ' : s[i];
    }
    out[j] = 0;
    return out;
}
static const char *g_form = "";
static char *rt_form(const char *name) {
    const char *p = g_form;
    while (*p) {
        const char *end = strchr(p, '&');
        if (!end) end = p + strlen(p);
        const char *eq = (const char *)memchr(p, '=', (size_t)(end - p));
        if (eq) {
            char *key = rt_url_decode(p, (size_t)(eq - p));
            int matches = strcmp(key, name) == 0;
            free(key);
            if (matches) return rt_url_decode(eq + 1, (size_t)(end - eq - 1));
        }
        p = *end ? end + 1 : end;
    }
    return strdup("");
}
#ifdef _WIN32
typedef SOCKET KiteSocket;
#else
typedef int KiteSocket;
#endif
static int rt_send_all(KiteSocket sock, const char *data, size_t length) {
    while (length) {
        int chunk = length > 65536 ? 65536 : (int)length;
#ifdef MSG_NOSIGNAL
        int sent = (int)send(sock, data, chunk, MSG_NOSIGNAL);
#else
        int sent = (int)send(sock, data, chunk, 0);
#endif
        if (sent <= 0) return 0;
        data += sent;
        length -= (size_t)sent;
    }
    return 1;
}
static void rt_serve(double port, const char *(*handler)(void), int line) {
    if (!isfinite(port) || port < 1 || port > 65535 || trunc(port) != port)
        rt_fail("端口须为 1 到 65535 的整数", line);
#ifdef _WIN32
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) rt_fail("无法启动网络", line);
    SOCKET srv = socket(AF_INET, SOCK_STREAM, 0);
    if (srv == INVALID_SOCKET) rt_fail("无法创建套接字", line);
    int one = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, (const char *)&one, sizeof one);
#else
    int srv = socket(AF_INET, SOCK_STREAM, 0);
    if (srv < 0) rt_fail("无法创建套接字", line);
#ifndef MSG_NOSIGNAL
    signal(SIGPIPE, SIG_IGN);
#endif
    int one = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
#endif
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof addr);
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port = htons((unsigned short)port);
    if (bind(srv, (struct sockaddr *)&addr, sizeof addr) != 0) {
        fprintf(stderr, "出错了：端口 %d 用不了（可能被别的程序占了）\n", (int)port);
        exit(1);
    }
    if (listen(srv, 16) != 0) rt_fail("无法监听端口", line);
    printf("界面已启动：http://localhost:%d\n", (int)port);
    fflush(stdout);
    for (;;) {
#ifdef _WIN32
        SOCKET c = accept(srv, NULL, NULL);
        if (c == INVALID_SOCKET) continue;
#else
        int c = accept(srv, NULL, NULL);
        if (c < 0) continue;
#endif
#ifdef _WIN32
        DWORD timeout = 2000;
        setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, (const char *)&timeout, sizeof timeout);
        setsockopt(c, SOL_SOCKET, SO_SNDTIMEO, (const char *)&timeout, sizeof timeout);
#else
        struct timeval timeout = {2, 0};
        setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof timeout);
        setsockopt(c, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof timeout);
#endif
        char buf[8192];
        size_t used = 0;
        buf[0] = 0;
        while (used < sizeof buf - 1 && !strstr(buf, "\r\n\r\n")) {
            int got = (int)recv(c, buf + used, (int)(sizeof buf - 1 - used), 0);
            if (got <= 0 || memchr(buf + used, 0, (size_t)got)) { buf[used] = 0; break; }
            used += (size_t)got;
            buf[used] = 0;
        }
        char *line_end = strstr(buf, "\r\n");
        if (strstr(buf, "\r\n\r\n") && line_end && strncmp(buf, "GET /", 5) == 0) {
            *line_end = 0;
            char *end = strchr(buf + 4, ' ');
            if (end && strncmp(end + 1, "HTTP/1.", 7) == 0) {
                *end = 0;
                const char *query = strchr(buf + 4, '?');
                g_form = query ? query + 1 : "";
                const char *body = handler();
                g_form = "";
                size_t blen = strlen(body);
                char head[256];
                int hlen = snprintf(head, sizeof head,
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: text/html; charset=utf-8\r\n"
                    "Content-Length: %zu\r\n"
                    "Connection: close\r\n\r\n", blen);
                if (rt_send_all(c, head, (size_t)hlen)) rt_send_all(c, body, blen);
            }
        }
#ifdef _WIN32
        closesocket(c);
#else
        close(c);
#endif
    }
}
static char *rt_bin(double v) {
    long long n = (long long)v;
    int neg = n < 0;
    unsigned long long m = neg ? (unsigned long long)(-n) : (unsigned long long)n;
    char tmp[80];
    int i = 0;
    if (m == 0) tmp[i++] = '0';
    while (m) { tmp[i++] = (char)('0' + (m & 1)); m >>= 1; }
    char *out = (char *)malloc((size_t)i + 2);
    int j = 0;
    if (neg) out[j++] = '-';
    while (i > 0) out[j++] = tmp[--i];
    out[j] = 0;
    return out;
}
'''

# ============================================================ 代码生成

def c_name(name):
    return "kite_u_" + name.encode("utf-8").hex()


def c_string(s):
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


def num_literal(v):
    if isinstance(v, int):
        return "%d.0" % v
    return repr(float(v))


def block_has_assign(node):
    """循环体里有没有改动任何变量"""
    if isinstance(node, Assign):
        return True
    if isinstance(node, Block):
        return any(block_has_assign(x) for x in node.stmts)
    if isinstance(node, If):
        if any(block_has_assign(b) for _, b in node.branches):
            return True
        return node.orelse is not None and block_has_assign(node.orelse)
    if isinstance(node, Loop):
        return block_has_assign(node.body)
    return False


class Gen:
    def __init__(self, ptypes, rtypes):
        self.ptypes = ptypes
        self.rtypes = rtypes
        self.out = []
        self.ind = 0
        self.scopes = [{}]
        self.ret = VOID
        self.in_func = False
        self.tmpn = 0
        self.warnings = []
        self.params = set()
        self.records = {}

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
        self.scopes[-1][name] = (t, c_name(name))

    def lookup(self, name, line):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        raise KiteError("「%s」还没有定义" % name, line)

    def new_tmp(self):
        self.tmpn += 1
        return "kite_t%d" % self.tmpn

    # -- 生成

    def show_fn(self, t):
        if t == NUM + "[][]":
            return "rt_show_mat_num"
        if t == STR + "[][]":
            return "rt_show_mat_str"
        return "rt_show_num" if elem_of(t) == NUM else "rt_show_str"

    def to_str(self, code, t):
        if t == STR:
            return code
        if t == NUM:
            return "rt_str_num(%s)" % code
        if elem_of(t) is not None:
            return "%s(%s)" % (self.show_fn(t), code)
        raise KiteError("这个值不能当文本用")

    def gen_expr(self, n):
        t = type(n)

        if t is Num:
            return (num_literal(n.value), NUM)

        if t is Text:
            return (c_string(n.value), STR)

        if t is Interp:
            pieces = []
            for p in n.parts:
                code, ty = self.gen_expr(p)
                pieces.append(self.to_str(code, ty))
            acc = pieces[0]
            for p in pieces[1:]:
                acc = "rt_cat(%s, %s)" % (acc, p)
            return (acc, STR)

        if t is Name:
            ty, cname = self.lookup(n.id, n.line)
            return (cname, ty)

        if t is ListLit:
            if not n.items:
                raise KiteError("空数组不支持，至少写一个元素", n.line)
            if isinstance(n.items[0], ListLit):
                return self.gen_matrix_literal(n)
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
            if elem in self.records:
                typ = array_of(elem)
                return ("%s_make(%d, (%s[]){%s}, %d)"
                        % (self.c_type(typ), len(codes), self.c_type(elem), ", ".join(codes), n.line), typ)
            if elem == NUM:
                return ("rt_make_num(%d, (double[]){%s})"
                        % (len(codes), ", ".join(codes)), NUM + "[]")
            return ("rt_make_str(%d, (const char *[]){%s})"
                    % (len(codes), ", ".join(codes)), STR + "[]")

        if t is Unary:
            code, ty = self.gen_expr(n.operand)
            if n.op == "!":
                return ("((double)(!(%s)))" % code, NUM)
            if ty != NUM:
                raise KiteError("文本不能取负", n.line)
            return ("(-(%s))" % code, NUM)

        if t is BinOp:
            return self.gen_binop(n)

        if t is Slice:
            base, bty = self.gen_expr(n.target)
            f, ft = self.gen_expr(n.from_)
            to, tt = self.gen_expr(n.to)
            if ft != NUM or tt != NUM:
                raise KiteError("切片的两头要写数字", n.line)
            if bty == STR:
                return ("rt_slice_str(%s, %s, %s, %d)"
                        % (base, f, to, n.line), STR)
            if is_matrix(bty):
                raise KiteError("还不能切二维表", n.line)
            if bty == NUM + "[]":
                return ("rt_slice_num(%s, %s, %s, %d)"
                        % (base, f, to, n.line), NUM + "[]")
            if bty == STR + "[]":
                return ("rt_slice_arr(%s, %s, %s, %d)"
                        % (base, f, to, n.line), STR + "[]")
            if elem_of(bty) in self.records:
                return ("%s_slice(%s, %s, %s, %d)"
                        % (self.c_type(bty), base, f, to, n.line), bty)
            raise KiteError("切片只能用在文本或一维数组上", n.line)

        if t is Field:
            if n.owner is None:
                return self.gen_call(Call(Name(n.fallback or n.name, n.line), [n.target], n.line))
            target, _ = self.gen_expr(n.target)
            return "(%s).%s" % (target, c_name(n.name)), dict(self.records[n.owner].fields)[n.name]

        if t is Index:
            base, bty = self.gen_expr(n.target)
            idx, ity = self.gen_expr(n.index)
            e = elem_of(bty)
            if e is None:
                raise KiteError("只有数组才能用 [] 取元素", n.line)
            if ity != NUM:
                raise KiteError("数组下标要写数字", n.line)
            if e == NUM:
                getter = "rt_get_num"
            elif e == STR:
                getter = "rt_get_str"
            elif e == NUM + "[]":
                getter = "rt_row_num"
            elif e == STR + "[]":
                getter = "rt_row_str"
            elif e in self.records:
                getter = self.c_type(bty) + "_get"
            else:
                raise KiteError("最多支持二维数组", n.line)
            return ("%s((%s), (%s), %d)" % (getter, base, idx, n.line), e)

        if t is Call:
            return self.gen_call(n)

        raise KiteError("内部错误：不认识的表达式", getattr(n, "line", 0))

    def gen_matrix_literal(self, n):
        rows = n.items
        cols = len(rows[0].items)
        if cols == 0:
            raise KiteError("二维数组的每一行不能是空的", n.line)
        flat = []
        elem = None
        for row in rows:
            if not isinstance(row, ListLit):
                raise KiteError("二维数组的每一行都要写成 [ ... ]", row.line)
            if len(row.items) != cols:
                raise KiteError("二维数组每行的长度要一样", row.line)
            for item in row.items:
                code, ty = self.gen_expr(item)
                if elem_of(ty) is not None:
                    raise KiteError("最多支持二维数组", item.line)
                if elem is None:
                    elem = ty
                elif elem != ty:
                    raise KiteError("二维数组里的元素类型要一致", item.line)
                flat.append(code)
        if elem == NUM:
            return ("(NumMat){(double[]){%s}, %d, %d}"
                    % (", ".join(flat), len(rows), cols), NUM + "[][]")
        return ("(StrMat){(const char *[]){%s}, %d, %d}"
                % (", ".join(flat), len(rows), cols), STR + "[][]")

    def gen_binop(self, n):
        op = n.op

        if op == "..":
            raise KiteError("1..5 这种范围只能写在 rp 后面", n.line)

        left, lt = self.gen_expr(n.left)
        right, rt = self.gen_expr(n.right)

        if op == "+":
            if lt == STR or rt == STR:
                return ("rt_cat(%s, %s)" % (self.to_str(left, lt),
                                            self.to_str(right, rt)), STR)
            return ("((%s) + (%s))" % (left, right), NUM)

        if op in ("-", "*", "/"):
            return ("((%s) %s (%s))" % (left, op, right), NUM)

        if op == "%":
            return ("fmod((%s), (%s))" % (left, right), NUM)

        if op in ("==", "!="):
            if lt == STR and rt == STR:
                return ("((double)(strcmp(%s, %s) %s 0))"
                        % (left, right, "==" if op == "==" else "!="), NUM)
            return ("((double)((%s) %s (%s)))" % (left, op, right), NUM)

        if op in ("<", ">", "<=", ">="):
            if lt == STR and rt == STR:
                return ("((double)(strcmp(%s, %s) %s 0))" % (left, right, op), NUM)
            return ("((double)((%s) %s (%s)))" % (left, op, right), NUM)

        if op in ("&&", "||"):
            c = "&&" if op == "&&" else "||"
            return ("((double)((%s) %s (%s)))" % (left, c, right), NUM)

        raise KiteError("不认识的运算符 %s" % op, n.line)

    def gen_call(self, n):
        if not isinstance(n.callee, Name):
            raise KiteError("只能调用有名字的函数", n.line)
        name = n.callee.id
        if name == "serve":
            return self.gen_serve(n)
        if name == "push":
            return self.gen_push(n)
        args = [self.gen_expr(a) for a in n.args]

        if name in BUILTINS:
            return self.gen_builtin(name, args, n.line)

        if name in self.records:
            return "(%s){%s}" % (self.c_type(name), ", ".join(c for c, _ in args)), name

        fn_params = self.ptypes[name]
        if len(args) != len(fn_params):
            raise KiteError("%s 需要 %d 个参数，这里给了 %d 个"
                            % (name, len(fn_params), len(args)), n.line)
        for i, (code, aty) in enumerate(args):
            if aty != fn_params[i]:
                raise KiteError("%s 的第 %d 个参数要%s，给的是%s"
                                % (name, i + 1, type_cn(fn_params[i]),
                                   type_cn(aty)), n.line)
        call = "%s(%s)" % (self.external_symbols.get(name, c_name(name)), ", ".join(c for c, _ in args))
        return (call, self.rtypes[name])

    def gen_push(self, n):
        if len(n.args) != 2:
            raise KiteError("push 要两个参数：数组、要加的值", n.line)
        target = n.args[0]
        if not isinstance(target, Name):
            raise KiteError("push 要作用在变量上，比如 xs.push(3)", n.line)
        ty, cname = self.lookup(target.id, n.line)
        if is_matrix(ty) or elem_of(ty) is None:
            raise KiteError("只有一维数组才能 push", n.line)
        code, vt = self.gen_expr(n.args[1])
        e = elem_of(ty)
        if vt != e:
            raise KiteError("数组元素是%s，不能 push 进去%s"
                            % (type_cn(e), type_cn(vt)), n.line)
        fn = self.c_type(ty) + "_push" if e in self.records else (
            "rt_push_num" if e == NUM else "rt_push_str")
        return ("%s(&%s, %s, %d)" % (fn, cname, code, n.line), VOID)

    def gen_serve(self, n):
        if len(n.args) != 2:
            raise KiteError("serve 要两个参数：端口、处理函数名", n.line)
        port, pt = self.gen_expr(n.args[0])
        if pt != NUM:
            raise KiteError("serve 的端口要写数字，比如 serve(8080, page)", n.line)
        h = n.args[1]
        if not isinstance(h, Name) or h.id not in self.rtypes:
            raise KiteError("serve 的第二个参数要写一个函数名", n.line)
        if self.ptypes[h.id] or self.rtypes[h.id] != STR:
            raise KiteError("serve 用的函数不能带参数，而且要返回文本（页面内容）",
                            n.line)
        return ("rt_serve(%s, %s, %d)" % (port, c_name(h.id), n.line), VOID)

    def gen_builtin(self, name, args, line):
        n = len(args)

        if name == "len":
            if n != 1:
                raise KiteError("len 只接受一个参数", line)
            code, ty = args[0]
            if ty == STR:
                return ("(double)rt_text_len(%s)" % code, NUM)
            if is_matrix(ty):
                return ("(double)((%s).rows)" % code, NUM)
            e = elem_of(ty)
            if e is not None:
                return ("(double)((%s).n)" % code, NUM)
            raise KiteError("len 只能量文本或数组", line)

        if name == "txt":
            if n != 1:
                raise KiteError("txt 只接受一个参数", line)
            code, ty = args[0]
            return (self.to_str(code, ty), STR)

        if name == "num":
            if n != 1:
                raise KiteError("num 只接受一个参数", line)
            code, ty = args[0]
            if ty != STR:
                raise KiteError("num 要一个文本", line)
            return ("rt_num(%s, %d)" % (code, line), NUM)

        if name in ("up", "low", "trim", "read"):
            if n != 1:
                raise KiteError("%s 只接受一个参数" % name, line)
            code, ty = args[0]
            if ty != STR:
                raise KiteError("%s 要一个文本" % name, line)
            cname = {"up": "rt_upper", "low": "rt_lower",
                     "trim": "rt_trim", "read": "rt_read"}[name]
            return ("%s(%s)" % (cname, code), STR)

        if name == "write":
            if n != 2:
                raise KiteError("write 要两个参数：路径、内容", line)
            if args[0][1] != STR or args[1][1] != STR:
                raise KiteError("write 的两个参数都要是文本", line)
            return ("rt_write(%s, %s)" % (args[0][0], args[1][0]), VOID)

        # ---- 交互 ----
        if name == "ask":
            if n == 0:
                return ('rt_ask("")', STR)
            if n != 1:
                raise KiteError("ask 最多带一句提示语", line)
            if args[0][1] != STR:
                raise KiteError("ask 的提示语要写文本，比如 ask(\"名字：\")", line)
            return ("rt_ask(%s)" % args[0][0], STR)

        if name == "rand":
            if n != 1:
                raise KiteError("rand 要一个数：想要的范围上限", line)
            if args[0][1] != NUM:
                raise KiteError("rand 的上限要写数字", line)
            return ("rt_rand(%s)" % args[0][0], NUM)

        if name == "seed":
            if n != 1:
                raise KiteError("seed 要一个数字", line)
            if args[0][1] != NUM:
                raise KiteError("seed 要一个数字", line)
            return ("rt_seed(%s)" % args[0][0], VOID)

        if name == "mat":
            if n != 3:
                raise KiteError("mat 要三个参数：行数、列数、填充值", line)
            (r, rt_), (c, ct), (v, vt) = args
            if rt_ != NUM or ct != NUM:
                raise KiteError("mat 的行数和列数要写数字", line)
            if vt == NUM:
                return ("rt_matrix_num(%s, %s, %s, %d)"
                        % (r, c, v, line), NUM + "[][]")
            if vt == STR:
                return ("rt_matrix_str(%s, %s, %s, %d)"
                        % (r, c, v, line), STR + "[][]")
            raise KiteError("mat 的填充值要么是数字，要么是文本", line)

        # ---- 数学 ----
        if name in ("abs", "floor", "round", "sqrt"):
            if n != 1:
                raise KiteError("%s 要一个数字" % name, line)
            code, ty = args[0]
            if ty != NUM:
                raise KiteError("%s 要一个数字" % name, line)
            if name == "sqrt":
                return ("rt_sqrt(%s, %d)" % (code, line), NUM)
            return ("rt_%s(%s)" % (name, code), NUM)

        if name == "pow":
            if n != 2 or args[0][1] != NUM or args[1][1] != NUM:
                raise KiteError("pow 要两个数字", line)
            return ("pow(%s, %s)" % (args[0][0], args[1][0]), NUM)

        # ---- 文本 ----
        if name == "rep":
            if n != 2 or args[0][1] != STR or args[1][1] != NUM:
                raise KiteError("rep 要：文本、重复几次", line)
            return ("rt_rep(%s, %s, %d)" % (args[0][0], args[1][0], line), STR)

        if name == "find":
            if n != 2 or args[0][1] != STR or args[1][1] != STR:
                raise KiteError("find 要两个文本：在哪找、找什么", line)
            return ("rt_find(%s, %s)" % (args[0][0], args[1][0]), NUM)

        if name == "sub":
            if (n != 3 or args[0][1] != STR
                    or args[1][1] != NUM or args[2][1] != NUM):
                raise KiteError("sub 要：文本、起点、长度", line)
            return ("rt_sub(%s, %s, %s, %d)"
                    % (args[0][0], args[1][0], args[2][0], line), STR)

        if name == "repl":
            if (n != 3 or args[0][1] != STR
                    or args[1][1] != STR or args[2][1] != STR):
                raise KiteError("repl 要三个文本：原文、被替换的、换成什么", line)
            return ("rt_repl(%s, %s, %s)"
                    % (args[0][0], args[1][0], args[2][0]), STR)

        # ---- 时间 ----
        if name in ("now", "date", "ts"):
            if n != 0:
                raise KiteError("%s 不用参数" % name, line)
            if name == "ts":
                return ("rt_ts()", NUM)
            return ("rt_%s()" % name, STR)

        # ---- 文件 ----
        if name == "exist":
            if n != 1 or args[0][1] != STR:
                raise KiteError("exist 要一个文本路径", line)
            return ("rt_exist(%s)" % args[0][0], NUM)

        if name == "del":
            if n != 1 or args[0][1] != STR:
                raise KiteError("del 要一个文本路径", line)
            return ("rt_del(%s)" % args[0][0], VOID)

        if name == "form":
            if n != 1 or args[0][1] != STR:
                raise KiteError("form 要一个文本：输入框的名字", line)
            return ("rt_form(%s)" % args[0][0], STR)

        if name == "html":
            return ("rt_html(%s)" % args[0][0], STR)

        # ---- 进制 ----
        if name in ("hex", "bin"):
            if n != 1 or args[0][1] != NUM:
                raise KiteError("%s 要一个数字" % name, line)
            return ("rt_%s(%s)" % (name, args[0][0]), STR)

        # ---- 常用算法 ----
        if name in ("sum", "avg", "max", "min"):
            if n != 1:
                raise KiteError("%s 只要一个数组参数" % name, line)
            code, ty = args[0]
            if ty != NUM + "[]":
                raise KiteError("%s 只能算数字数组" % name, line)
            fn = {"sum": "rt_sum", "avg": "rt_avg",
                  "max": "rt_max", "min": "rt_min"}[name]
            return ("%s(%s)" % (fn, code), NUM)

        if name == "sort":
            if n != 1:
                raise KiteError("sort 只要一个数组参数", line)
            code, ty = args[0]
            if ty == NUM + "[]":
                return ("rt_sort_num(%s)" % code, VOID)
            if ty == STR + "[]":
                return ("rt_sort_str(%s)" % code, VOID)
            raise KiteError("sort 只能排数字数组或文本数组", line)

        if name == "join":
            if n not in (1, 2):
                raise KiteError("join 要 1 或 2 个参数：数组、分隔符（默认逗号）", line)
            if n == 1:
                args = [args[0], ('","', STR)]
            (a, at), (sep, st) = args
            if st != STR:
                raise KiteError('join 的分隔符要写文本，比如 ","', line)
            if at == NUM + "[]":
                return ("rt_join_num(%s, %s)" % (a, sep), STR)
            if at == STR + "[]":
                return ("rt_join_str(%s, %s)" % (a, sep), STR)
            raise KiteError("join 的第一个参数要是数组", line)

        if name == "split":
            if n not in (1, 2):
                raise KiteError("split 要 1 或 2 个参数：文本、分隔符（默认逗号）", line)
            if n == 1:
                args = [args[0], ('","', STR)]
            if args[0][1] != STR or args[1][1] != STR:
                raise KiteError("split 的两个参数都要是文本", line)
            return ("rt_split(%s, %s)" % (args[0][0], args[1][0]), STR + "[]")

        if name in ("times", "has"):
            if n != 2:
                raise KiteError("%s 要两个参数：数组、要找的值" % name, line)
            (a, at), (val, vt) = args
            if at == NUM + "[]":
                if vt != NUM:
                    raise KiteError("%s 在数字数组里找数字" % name, line)
                fn = "rt_count_num" if name == "times" else "rt_contains_num"
                return ("%s(%s, %s)" % (fn, a, val), NUM)
            if at == STR + "[]":
                if vt != STR:
                    raise KiteError("%s 在文本数组里找文本" % name, line)
                fn = "rt_count_str" if name == "times" else "rt_contains_str"
                return ("%s(%s, %s)" % (fn, a, val), NUM)
            raise KiteError("%s 的第一个参数要是数组" % name, line)

        raise KiteError("内部错误：没有这个内置函数 %s" % name, line)

    # -- 语句

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
            self.emit("%s;" % code)
            return

        if t is Assign:
            self.gen_assign(node)
            return

        if t is Say:
            self.gen_say(node)
            return

        if t is If:
            self.gen_if(node)
            return

        if t is Loop:
            self.gen_loop(node)
            return

        if t is Return:
            if not self.in_func:
                raise KiteError("ret 只能写在函数里", node.line)
            if node.expr is None:
                self.emit("return;")
                return
            code, ty = self.gen_expr(node.expr)
            self.emit("return %s; /* kite:%d */" % (code, node.line))
            return

        if t is Break:
            self.emit("break;")
            return

        if t is Continue:
            self.emit("continue;")
            return

        if t is FnDef:
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
            if e != ty:
                raise KiteError("数组元素是%s，不能放%s进去"
                                % (type_cn(e), type_cn(ty)), node.line)
            if e == NUM:
                setter = "rt_set_num"
            elif e == STR:
                setter = "rt_set_str"
            elif e in self.records:
                setter = self.c_type(bty) + "_set"
            else:
                raise KiteError("不能整行赋值，用 m[i][j] = ... 一个个改", node.line)
            self.emit("%s((%s), (%s), %s, %d); /* kite:%d */"
                      % (setter, base, idx, code, node.line, node.line))
            return

        name = node.target.id
        found = None
        for s in reversed(self.scopes):
            if name in s:
                found = s[name]
                break

        if found is None:
            if ty == VOID:
                raise KiteError("这个表达式没有值，不能赋给变量", node.line)
            self.declare(name, ty, node.line)
            self.emit("%s %s = %s; /* kite:%d */"
                      % (self.c_type(ty), c_name(name), code, node.line))
            return

        ety, cname = found
        if ety != ty:
            raise KiteError("「%s」是%s，不能把%s放进去"
                            % (name, type_cn(ety), type_cn(ty)), node.line)
        if elem_of(ety) is not None:
            raise KiteError("数组不能整个重新赋值（用 xs[1] = ... 一个个改）",
                            node.line)
        self.emit("%s = %s; /* kite:%d */" % (cname, code, node.line))

    def gen_say(self, node):
        args = []
        for expr in node.exprs:
            code, ty = self.gen_expr(expr)
            tmp = self.new_tmp()
            if ty == NUM:
                self.emit("char %s[64];" % tmp)
                self.emit("rt_format_num(%s, %s);" % (tmp, code))
            else:
                self.emit("const char *%s = %s;" % (tmp, self.to_str(code, ty)))
            args.append(tmp)
        fmt = " ".join(["%s"] * len(args)) + "\n"
        self.emit("printf(%s, %s); /* kite:%d */"
                  % (c_string(fmt), ", ".join(args), node.line))

    def gen_if(self, node):
        first = True
        for cond, body in node.branches:
            code, ty = self.gen_expr(cond)
            keyword = "if" if first else "} else if"
            self.emit("%s (%s) { /* kite:%d */" % (keyword, code, node.line))
            self.gen_block(body)
            first = False
        if node.orelse is not None:
            self.emit("} else {")
            self.gen_block(node.orelse)
        self.emit("}")

    def gen_loop(self, node):
        source_name = node.name or "count"
        name = self.new_tmp()

        # rp ut 条件
        if node.mode == "until":
            code, ty = self.gen_expr(node.source)
            if ty != NUM:
                raise KiteError("ut 后面要写一个条件，比如 n <= 0", node.line)
            if not block_has_assign(node.body):
                self.warnings.append(
                    "第 %d 行的 rp ut 循环里没有任何变量被改动，可能会一直重复"
                    % node.line)
            self.emit("while (!(%s)) { /* kite:%d 重复直到条件成立 */"
                      % (code, node.line))
            self.gen_block(node.body)
            self.emit("}")
            return

        src = node.source

        # rp 1..10
        if isinstance(src, BinOp) and src.op == "..":
            a, at = self.gen_expr(src.left)
            b, bt = self.gen_expr(src.right)
            lo, hi, step = self.new_tmp(), self.new_tmp(), self.new_tmp()
            self.emit("{ /* kite:%d */" % node.line)
            self.ind += 1
            self.emit("double %s = (%s);" % (lo, a))
            self.emit("double %s = (%s);" % (hi, b))
            self.emit("double %s = %s <= %s ? 1 : -1;" % (step, lo, hi))
            self.emit("for (double %s = %s; isfinite(%s) && isfinite(%s) && "
                      "(%s > 0 ? %s <= %s : %s >= %s); %s = rt_step(%s, %s)) {"
                      % (name, lo, name, hi, step, name, hi, name, hi,
                         name, name, step))
            self.push()
            self.scopes[-1][source_name] = (NUM, name)
            self.ind += 1
            for stmt in node.body.stmts:
                self.gen_stmt(stmt)
            self.ind -= 1
            self.pop()
            self.emit("}")
            self.ind -= 1
            self.emit("}")
            return

        seq, st = self.gen_expr(src)

        # rp 5 —— 重复 5 次
        if st == NUM:
            tmp = self.new_tmp()
            self.emit("{ /* kite:%d 重复 */" % node.line)
            self.ind += 1
            self.emit("double %s = (%s);" % (tmp, seq))
            self.emit("for (double %s = 1; isfinite(%s) && %s <= %s; %s = rt_step(%s, 1)) {"
                      % (name, tmp, name, tmp, name, name))
            self.push()
            self.scopes[-1][source_name] = (NUM, name)
            self.ind += 1
            for stmt in node.body.stmts:
                self.gen_stmt(stmt)
            self.ind -= 1
            self.pop()
            self.emit("}")
            self.ind -= 1
            self.emit("}")
            return

        # rp xs —— 遍历数组
        e = elem_of(st)
        if e is None:
            raise KiteError("rp 后面要么是次数、1..5、或者一个数组", node.line)
        self.emit("{ /* kite:%d 遍历数组 */" % node.line)
        self.ind += 1
        if isinstance(src, Name):
            arr = seq
        else:
            arr = self.new_tmp()
            self.emit("%s %s = %s;" % (self.c_type(st), arr, seq))
        if is_matrix(st):
            self.emit("for (int __i = 1; __i <= (%s).rows; __i++) {" % arr)
            self.push()
            self.scopes[-1][source_name] = (e, name)
            self.ind += 1
            getter = "rt_row_num" if e == NUM + "[]" else "rt_row_str"
            self.emit("%s %s = %s(%s, __i, %d);"
                      % (self.c_type(e), name, getter, arr, node.line))
        else:
            self.emit("for (int __i = 1; __i <= (%s).n; __i++) {" % arr)
            self.push()
            self.scopes[-1][source_name] = (e, name)
            self.ind += 1
            self.emit("%s %s = (%s).v[__i - 1];" % (self.c_type(e), name, arr))
        for stmt in node.body.stmts:
            self.gen_stmt(stmt)
        self.ind -= 1
        self.pop()
        self.emit("}")
        self.ind -= 1
        self.emit("}")

    def c_type(self, t):
        if t in self.records:
            return c_name(t)
        if elem_of(t) in self.records:
            return c_name(elem_of(t)) + "_array"
        if t == VOID:
            return "void"
        if t == NUM + "[][]":
            return "NumMat"
        if t == STR + "[][]":
            return "StrMat"
        if t == NUM + "[]":
            return "NumArr"
        if t == STR + "[]":
            return "StrArr"
        if t == NUM:
            return "double"
        if t == STR:
            return "const char *"
        raise KiteError("内部错误：没有这种类型 %s" % t)

    # -- 函数与整个程序

    def gen_function(self, fn):
        self.scopes = [{}]
        self.ind = 1
        self.ret = self.rtypes[fn.name]
        self.in_func = True

        self.params = set()
        for (pname, _), ty in zip(fn.params, self.ptypes[fn.name]):
            self.scopes[-1][pname] = (ty, c_name(pname))
            self.params.add(pname)

        for stmt in fn.body.stmts:
            self.gen_stmt(stmt)

        self.in_func = False
        return self.out

    def build(self, program, ptypes, rtypes, record_order=()):
        self.ptypes = ptypes
        self.rtypes = rtypes

        header = ["/* 由 kite 自动生成，别直接改这个文件，改 .kite 源文件 */",
                  RUNTIME, ""]

        self.records = {record.name: record for record in record_order}
        for record in record_order:
            header.append("typedef struct {")
            for field, typ in record.fields:
                header.append("    %s %s;" % (self.c_type(typ), c_name(field)))
            header.append("} %s;" % c_name(record.name))
            header.append("KITE_RECORD_ARRAY(%s, %s)" % (
                self.c_type(record.name), self.c_type(array_of(record.name))))
        header.append("")

        self.external_symbols = {stmt.name: stmt.symbol for stmt in program.stmts if isinstance(stmt, ExternDef)}
        protos = []
        for stmt in program.stmts:
            if isinstance(stmt, ExternDef):
                params = ", ".join("double" for _ in stmt.params) or "void"
                protos.append("extern double %s(%s);" % (stmt.symbol, params))
            if isinstance(stmt, FnDef):
                params = ", ".join("%s %s" % (self.c_type(pt), c_name(pn))
                                   for (pn, _), pt in zip(stmt.params,
                                                          ptypes[stmt.name]))
                if not params:
                    params = "void"
                protos.append("%s %s(%s);" % (self.c_type(rtypes[stmt.name]),
                                              c_name(stmt.name), params))
        header.extend(protos)
        header.append("")

        top = [s for s in program.stmts if not isinstance(s, (FnDef, RecordDef, ExternDef))]
        self.out = []
        self.scopes = [{}]
        self.ind = 1
        self.in_func = False
        for stmt in top:
            self.gen_stmt(stmt)
        self.emit("return 0;")
        main_body = self.out

        main_lines = ["int main(void) {"] + main_body + ["}", ""]

        func_lines = []
        for stmt in program.stmts:
            if isinstance(stmt, FnDef):
                self.out = []
                gen = self.gen_function(stmt)
                params = ", ".join("%s %s" % (self.c_type(pt), c_name(pn))
                                   for (pn, _), pt in zip(stmt.params,
                                                          ptypes[stmt.name]))
                if not params:
                    params = "void"
                func_lines.append("%s %s(%s) { /* kite:%d */"
                                  % (self.c_type(rtypes[stmt.name]), c_name(stmt.name),
                                     params, stmt.line))
                func_lines.extend(gen)
                func_lines.append("}")
                func_lines.append("")

        return "\n".join(header + main_lines + func_lines)


# ============================================================ 命令行

def load_program(src, path=None):
    from kite_modules import load_program as link_program
    return link_program(src, path, core=sys.modules[__name__])


def require_backend(program, target):
    for stmt in program.stmts:
        if isinstance(stmt, ExternDef):
            raise KiteError("%s 后端不支持 extern c" % target, stmt.line, getattr(stmt, "source_path", None))


def compile_source(src, path=None):
    program = load_program(src, path)
    typer = Typer(program)
    ptypes, rtypes = typer.run()
    gen = Gen(ptypes, rtypes)
    code = gen.build(program, ptypes, rtypes, typer.record_order)
    return code, gen.warnings


def main(argv):
    parser = argparse.ArgumentParser(description="将 Kite 转译为 C、JavaScript、Java 或 Unity C#")
    parser.add_argument("path", help="Kite 源文件（UTF-8）")
    targets = parser.add_mutually_exclusive_group()
    for flag in ("--run", "--exe", "--js", "--java", "--unity"):
        targets.add_argument(flag, action="store_true")
    parser.add_argument("-o", metavar="路径", help="指定生成文件路径")
    parser.add_argument("--link", action="append", default=[], metavar="文件",
                        help="为 --run 或 --exe 链接 C 源文件、对象文件或静态库，可重复使用")
    args = parser.parse_args(argv[1:])
    if args.link and not (args.run or args.exe):
        parser.error("--link 需要 --run 或 --exe")
    link_files = [os.path.abspath(filename) for filename in args.link]
    for filename in link_files:
        if not os.path.isfile(filename):
            parser.error("找不到要链接的文件：" + filename)
    path = args.path
    if __name__ == "__main__":
        sys.modules.setdefault("kite", sys.modules[__name__])
    try:
        with open(path, encoding="utf-8-sig") as f:
            src = f.read()
    except UnicodeDecodeError:
        print("读不了这个文件：请将 Kite 源文件另存为 UTF-8", file=sys.stderr)
        return 2
    except OSError as e:
        print("读不了这个文件：" + str(e), file=sys.stderr)
        return 2

    base = os.path.splitext(path)[0]
    warnings = []
    try:
        if args.js:
            from kite_js import generate
            out = args.o or base + ".js"
            code = generate(src, path)
        elif args.java or args.unity:
            if args.java:
                from kite_java import generate, class_name_for
                suffix = ".java"
            else:
                from kite_unity import generate, class_name_for
                suffix = ".cs"
            filename = class_name_for(path) + suffix
            out = args.o or os.path.join(os.path.dirname(path), filename)
            if os.path.basename(out) != filename:
                parser.error("输出文件名必须为 " + filename)
            code = generate(src, path)
        else:
            out = args.o or base + ".c"
            code, warnings = compile_source(src, path)
    except KiteError as e:
        print("出错了：" + e.msg, file=sys.stderr)
        error_src = src
        if e.path and os.path.normcase(os.path.realpath(e.path)) != os.path.normcase(os.path.realpath(path)):
            print("  文件：" + str(e.path), file=sys.stderr)
            try:
                with open(e.path, encoding="utf-8-sig") as f:
                    error_src = f.read()
            except (OSError, UnicodeDecodeError):
                error_src = ""
        lines = error_src.splitlines()
        if 1 <= e.line <= len(lines):
            print("  第 %d 行：%s" % (e.line, lines[e.line - 1]), file=sys.stderr)
        return 1

    def normalized(filename):
        return os.path.normcase(os.path.realpath(filename))

    if normalized(out) == normalized(path):
        parser.error("输出文件不能覆盖源文件")
    try:
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(code)
    except OSError as e:
        print("写不了输出文件：" + str(e), file=sys.stderr)
        return 2
    for message in warnings:
        print("提醒：" + message, file=sys.stderr)
    print("已生成 " + out, file=sys.stderr)

    if not (args.exe or args.run):
        return 0
    compiler = "x86_64-w64-mingw32-gcc" if args.exe else "gcc"
    if shutil.which(compiler) is None:
        print("没找到 %s，请安装并加入 PATH" % compiler, file=sys.stderr)
        return 1
    windows = args.exe or os.name == "nt"
    stem = os.path.splitext(out)[0]
    suffix = ".exe" if windows else ""
    exe = stem + suffix
    while normalized(exe) in {normalized(out), normalized(path)}:
        stem += ".bin"
        exe = stem + suffix
    flags = ["-static"] if args.exe else []
    libs = ["-lm", "-lws2_32"] if windows else ["-lm"]
    try:
        result = subprocess.run([compiler, "-O2", *flags, "-o", exe,
                                 "-x", "c", out, "-x", "none", *link_files, *libs])
        if result.returncode:
            print("C 编译失败", file=sys.stderr)
            return 1
        if args.exe:
            print("已生成 " + exe + "（Windows 程序）", file=sys.stderr)
            return 0
        return subprocess.run([os.path.abspath(exe)]).returncode
    except OSError as e:
        print("无法启动程序：" + str(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv))
