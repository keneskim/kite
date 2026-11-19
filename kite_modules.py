"""Load Kite source modules and link their declarations into one AST."""

import os
from pathlib import Path


def _parse(core, source, path):
    class ModuleParser(core.Parser):
        def at_use(self):
            token = self.peek()
            return token.value == "use" and (
                token.kind == "KW" or token.kind == "NAME" and self.peek(1).kind == "TEXT"
            )

        def parse_statement(self):
            if self.at_use():
                raise core.KiteError("use 只能写在文件开头", self.peek().line)
            return super().parse_statement()

        def parse_imports(self):
            imports = []
            self.skip_newlines()
            while self.at_use():
                line = self.advance().line
                raw = self.expect("TEXT").value
                raw = raw.replace(core.LBRACE, "{").replace(core.RBRACE, "}")
                target = Path(raw)
                if not raw or "\n" in raw or "\r" in raw or "\0" in raw or target.anchor:
                    raise core.KiteError("use 需要一个相对文件路径", line)
                self.expect("NAME", "as")
                alias = self.expect("NAME").value
                self.expect("NEWLINE")
                imports.append((target, alias, line))
                self.skip_newlines()
            return imports

    try:
        parser = ModuleParser(core.tokenize(source))
        imports = parser.parse_imports()
        return parser.parse_program(), imports
    except core.KiteError as error:
        error.path = path
        raise


class _Module:
    def __init__(self, program, path, prefix):
        self.program = program
        self.path = path
        self.prefix = prefix
        self.exports = {}
        self.aliases = {}


class _Loader:
    def __init__(self, core):
        self.core = core
        self.declarations = (core.FnDef, core.RecordDef)
        if hasattr(core, "ExternDef"):
            self.declarations += (core.ExternDef,)
        self.active = []
        self.loaded = {}
        self.linked = []
        self.entry = None
        self.next_module = 0

    def error(self, message, path, line):
        return self.core.KiteError(message, line, path)

    def load(self, source, path, *, entry=False):
        program, imports = _parse(self.core, source, path)
        prefix = ""
        if not entry:
            prefix = "::module%d::" % self.next_module
            self.next_module += 1
        module = _Module(program, path, prefix)
        if entry:
            self.entry = module
        for stmt in program.stmts:
            if not isinstance(stmt, self.declarations):
                if entry:
                    continue
                raise self.error("模块的顶层只能包含声明", path, stmt.line)
            name = stmt.name
            if not entry and name in module.exports:
                raise self.error("模块内重复定义「%s」" % name, path, stmt.line)
            if not entry and isinstance(stmt, self.core.RecordDef) and name in self.core.TYPE_NAMES:
                raise self.error("记录名「%s」已被使用" % name, path, stmt.line)
            module.exports[name] = prefix + name

        key = os.path.normcase(path) if path is not None else None
        self.active.append((key, path))
        for target, alias, line in imports:
            if alias in module.aliases:
                raise self.error("模块别名「%s」重复了" % alias, path, line)
            module.aliases[alias] = self.load_import(target, path, line)
        self.active.pop()

        self.link_node(program, module)
        if key is not None:
            self.loaded[key] = module
        if not entry:
            self.linked.extend(program.stmts)
        return module

    def load_import(self, target, importer, line):
        if importer is None:
            raise self.error("使用 use 时需要指定源文件路径", importer, line)
        try:
            path = (Path(importer).parent / target).resolve()
        except (OSError, RuntimeError, ValueError) as error:
            raise self.error("无法解析模块路径「%s」：%s" % (target, error), importer, line) from error
        path = str(path)
        key = os.path.normcase(path)
        for index, (active_key, _) in enumerate(self.active):
            if key == active_key:
                cycle = [item for _, item in self.active[index:]] + [path]
                raise self.error("模块循环引用：%s" % " -> ".join(cycle), importer, line)
        if key in self.loaded:
            return self.loaded[key]
        try:
            source = Path(path).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            raise self.error("无法读取模块「%s」：%s" % (target, error), importer, line) from error
        return self.load(source, path)

    def resolve(self, symbol, module, line, kind):
        if kind == "type" and symbol.endswith("[]"):
            return self.core.array_of(self.resolve(self.core.elem_of(symbol), module, line, kind))
        alias, separator, name = symbol.partition("::")
        if separator:
            imported = module.aliases.get(alias)
            if imported is None:
                raise self.error("没有模块别名「%s」" % alias, module.path, line)
            if name not in imported.exports:
                raise self.error("模块「%s」没有声明「%s」" % (alias, name), module.path, line)
            return imported.exports[name]
        if kind == "variable":
            if module.prefix and symbol in self.entry.exports:
                return module.prefix + "local::" + symbol
            return symbol
        if kind == "type" and symbol in self.core.TYPE_NAMES:
            return symbol
        if symbol in module.exports:
            return module.exports[symbol]
        if not module.prefix or kind == "field":
            return symbol
        if kind == "function" and (symbol in self.core.BUILTINS or symbol in self.core._UNITY_PARAMS):
            return symbol
        label = "类型" if kind == "type" else "函数"
        raise self.error("模块内没有叫「%s」的%s" % (symbol, label), module.path, line)

    def bind(self, name, module, line):
        if module.prefix and name in module.exports:
            raise self.error("「%s」是模块声明名，不能用作变量名" % name, module.path, line)
        return self.resolve(name, module, line, "variable")

    def link_node(self, node, module, kind="variable"):
        core = self.core
        node.source_path = module.path
        if isinstance(node, self.declarations):
            if node.name in module.exports:
                node.name = module.exports[node.name]
            if isinstance(node, core.RecordDef):
                node.fields = [(field, self.resolve(t, module, node.line, "type"))
                               for field, t in node.fields]
            else:
                node.params = [(self.bind(param, module, node.line),
                                self.resolve(t, module, node.line, "type") if t else t)
                               for param, t in node.params]
                if node.ret:
                    node.ret = self.resolve(node.ret, module, node.line, "type")

        if isinstance(node, core.Call):
            self.link_node(node.callee, module, "function")
            for index, arg in enumerate(node.args):
                arg_kind = "variable"
                if isinstance(node.callee, core.Name) and node.callee.id == "serve" and index == 1:
                    arg_kind = "function"
                self.link_node(arg, module, arg_kind)
            return
        if isinstance(node, core.Assign) and isinstance(node.target, core.Name):
            if "::" in node.target.id:
                raise self.error("不能给模块成员赋值", module.path, node.target.line)
            self.link_node(node.target, module, "binding")
            self.link_node(node.value, module)
            return
        if isinstance(node, core.Loop) and node.mode != "until":
            name = node.name or "count"
            linked_name = self.bind(name, module, node.line)
            if linked_name != name:
                node.name = linked_name
        if isinstance(node, core.Name):
            if kind == "binding":
                node.id = self.bind(node.id, module, node.line)
            else:
                node.id = self.resolve(node.id, module, node.line, kind)
        if isinstance(node, core.Field):
            fallback = self.resolve(node.name, module, node.line, "field")
            if fallback == node.name and module.prefix and node.name in self.entry.exports:
                fallback = module.prefix + node.name
            if fallback != node.name:
                node.fallback = fallback

        # All children live in node slots, possibly inside lists or tuples
        # (for example, an if statement's condition/body pairs).
        for slot in type(node).__slots__:
            self.link_value(getattr(node, slot), module)

    def link_value(self, value, module):
        if isinstance(value, self.core.Node):
            self.link_node(value, module)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self.link_value(item, module)


def load_program(src, path=None, *, core=None):
    """Parse source text and return a Block with its imported declarations linked.

    Supply the entry file path to enable relative imports. A caller executing
    the compiler as a script can supply its own core module for AST identity.
    """
    if core is None:
        if __package__:
            from . import kite as core
        else:
            import kite as core
    path = str(Path(path).resolve()) if path is not None else None
    loader = _Loader(core)
    entry = loader.load(src, path, entry=True)
    entry.program.stmts[:0] = loader.linked
    return entry.program


parse_program = load_program
