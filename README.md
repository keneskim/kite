# Kite

**用简洁的语法写程序，转译为 C、JavaScript、Java 或 Unity C#。**

Kite 是一门正在开发的静态类型语言。它采用缩进代码块、类型推断和字符串插值，以 `p` 打印、`rp` 循环、`ut` 表达“直到”、`ret` 返回值。你可以从单文件程序开始，再用模块、记录和记录数组组织更大的程序。

```kite
fn fib(n)
    if n < 2
        ret n
    ret fib(n - 1) + fib(n - 2)

p "fib(20) = {fib(20)}"

prices = [12, 18, 25]
total = 0
rp price in prices
    total = total + price
p "总价：{total}"
```

## 快速开始

下载或克隆本仓库，在仓库目录中运行以下命令。编译器使用 Python 标准库，不需要安装第三方 Python 包。

```sh
git clone https://github.com/keneskim/kite.git
cd kite
```

### JavaScript / Node.js

需要 Python 3 和支持 BigInt 的现代 Node.js：

```sh
python kite.py examples/hello.kite --js
node examples/hello.js
```

Linux/macOS 上可以将 `python` 换成 `python3`。浏览器也可以通过 `<script>` 加载生成的 JavaScript，但标准输入和本地文件操作需要 Node.js。

### C / 原生程序

需要 Python 3 和加入 PATH 的 GCC：

```sh
python kite.py examples/hello.kite --run
```

也可以只生成 C 源码，然后自行编译：

```sh
python kite.py examples/hello.kite -o hello.c
gcc -O2 hello.c -o hello -lm
```

在 Windows 上使用 GCC 时需额外链接 `-lws2_32`；`--run` 会自动添加。测试入口也支持已加载开发环境的 MSVC，普通 `--run` 命令仍使用 GCC。

### Java

需要 JDK 11 或更新版本：

```sh
python kite.py examples/hello.kite --java
javac -encoding UTF-8 examples/Hello.java
java -cp examples Hello
```

### Unity

```sh
python kite.py unity/game.kite --unity
```

生成的 C# 脚本可放入 Unity 项目。具体组件和场景设置见 [Unity 指南](docs/unity.md)。这个后端面向 Unity，支持的功能子集见下表。

## 语言一览

### 变量、判断和循环

第一次赋值创建变量，之后不能更换类型。条件使用数字，`0` 为假，非 `0` 为真。

```kite
hp = 30
rp ut hp <= 0
    hp = hp - 7
    p "剩余血量：{hp}"

rp 3
    p "第 {count} 次"

rp i in 5..1
    p i
```

`rp n` 的次数和范围两端在进入循环时各计算一次；范围包含两端，方向由端点决定。`rp item in items` 中的 `item` 是数组元素。

### 数组

下标从 **1** 开始，负下标从末尾计数；切片包含两端。

```kite
xs = [3, 1, 2]
xs.push(4)
p xs[1], xs[-1]

copy = xs[1..-1]
copy[1] = 99
p xs
p copy
```

数组不能直接互相赋值，使用切片获得独立副本。文本长度和切片按 Unicode 码点计算；`find`、`sub` 的位置则从 **0** 开始。

### 记录和记录数组

记录将相关数据组合成一个类型。字段不可变，可以构造新记录替换变量或数组元素。

```kite
record Hero
    name: string
    hp: number

fn hurt(hero: Hero, damage: number) -> Hero
    ret Hero(hero.name, hero.hp - damage)

team = [Hero("小明", 100), Hero("小红", 80)]
team.push(Hero("小蓝", 90))
team[1] = hurt(team[1], 20)

rp hero in team
    p "{hero.name}：{hero.hp} 血"
```

一维记录数组支持下标读写、追加、切片、长度和遍历，也能作为函数参数，例如 `fn heal(team: Hero[])`。

### 多文件模块

模块导入放在文件开头。路径相对于声明 `use` 的源文件，调用使用 `模块别名::名字`。

```kite
use "geo.kite" as geo

point = geo::Point(2, 3)
moved = geo::shift(point, 5)
p "({moved.x}, {moved.y})"
```

完整示例见 [模块入口](examples/modules/main.kite)、[坐标模块](examples/modules/geo.kite)和[记录数组示例](examples/modules/record_arrays.kite)。

### 调用外部 C 函数

C 后端支持显式声明宿主函数签名，并链接 C 源码、对象文件或静态库：

```kite
extern c fn scale(x: number) -> number = "host_scale"
p scale(7)
```

```sh
python kite.py program.kite --run --link helper.c
```

目前参数和返回值均仅支持 `number`，对应 C 的 `double`。宿主实现必须匹配声明；这不是对任意 C API 的自动绑定。详见 [C 外部函数](docs/modules.md#调用-c-外部函数)。

## 后端支持范围

| 功能 | C | JavaScript | Java | Unity C# |
|---|---|---|---|---|
| 数字、文本、判断、循环、函数 | 支持 | 支持 | 支持 | 支持 |
| 模块、不可变记录 | 支持 | 支持 | 支持 | 支持 |
| 一维记录数组 | 支持 | 支持 | 支持 | 支持 |
| 数字 / 文本数组和二维表 | 支持 | 支持 | 支持 | 暂不支持 |
| 键盘输入、文件操作 | 支持 | Node.js | 支持 | 暂不支持 |
| 本地网页 `serve` / `form` / `html` | 支持 | 暂不支持 | 暂不支持 | 暂不支持 |
| `extern c fn` | 支持 | 暂不支持 | 暂不支持 | 暂不支持 |
| Unity 输入和物理辅助函数 | — | — | — | 支持 |

不同目标的标准库和平台能力仍有差异，请结合对应指南使用。`--exe` 可通过 `x86_64-w64-mingw32-gcc` 生成 Windows 控制台程序。

## 示例与文档

- [入门教程和语法速查](docs/kite.md)：从打印、判断、循环学到文件和本地网页。
- [模块、记录、记录数组与外部 C 函数](docs/modules.md)。
- [JavaScript 指南](docs/js.md)、[Java 指南](docs/java.md)、[Unity 指南](docs/unity.md)。
- [猜数字](examples/guess.kite)、[数组](examples/arrays.kite)、[本地网页](examples/web.kite)。
- [待办清单](apps/todo.kite)：本地网页和文件存储。
- [八皇后](contest/1-queens.kite)、[大数阶乘](contest/2-factorial.kite)、[最长递增子序列](contest/3-lis.kite)：算法示例。

## 测试

在仓库目录运行：

```sh
python tests/run.py
python -m unittest discover -s tests -p test_modules.py
```

测试会将程序转译、编译、运行，再分别核对退出码和输出。所有生成文件放在自动清理的临时目录中。

可单独选择后端：

```sh
python tests/run.py --backend js
python tests/run.py --backend java
python tests/run.py --backend c
python tests/run.py --backend unity
```

默认跳过缺少工具的后端，并明确报告。显式指定后端时请阅读 [测试说明](tests/README.md)。Unity 测试使用 API 桩，不能代替真实编辑器和游戏场景测试。

## 项目结构

| 路径 | 内容 |
|---|---|
| `kite.py` | 词法、语法、类型检查、C 生成和命令行入口 |
| `kite_modules.py` | 模块加载、符号链接和依赖检查 |
| `kite_js.py` / `kite_java.py` / `kite_unity.py` | 其他目标后端 |
| `docs/` | 语言和后端文档 |
| `examples/` / `tutorial/` / `contest/` | 示例、练习和算法 |
| `apps/` / `unity/` | 小应用和 Unity 示例 |
| `tests/` | 跨后端回归、模块单元测试和 Unity API 桩 |

## 当前限制

Kite 仍在积极开发，语法和接口可能发生变化。

- 记录字段不可变，不能包含数组；不支持递归记录类型。
- 数组不能从函数返回，也不能建立变量别名；函数参数允许替换元素，禁止 `push`。
- 不支持空数组字面量；可以用已有数组的空切片获得同类型空数组。
- 记录数组仅支持一维，不能直接打印、比较、排序或 `join`；请遍历后处理字段。
- 数字使用双精度浮点，整数超过 `2^53` 无法保证精确；输出最多 15 位有效数字。
- C 后端尚无自动内存回收，长时间运行或频繁构造数组、拼接文本的程序需要留意内存增长。
- 导入模块的顶层只允许声明。没有包管理器、异常处理语法或通用的宿主库自动绑定。
- `serve` 是仅监听 `127.0.0.1` 的本地演示服务，不是生产级 Web 框架。

## 参与开发

欢迎提交 Issue 和 Pull Request。报告问题时，请附上最小 Kite 程序、生成命令、使用的后端、工具版本，以及实际输出和预期输出。

修改编译器时，请补充能体现行为的测试；跨后端功能应同时检查支持它的各个后端。

## 许可证

Copyright © 2026 keneskim。项目采用 [MIT License](LICENSE)。
