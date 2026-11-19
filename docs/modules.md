# 模块、记录与 C 外部函数

## 导入模块

在文件开头用 `use "path.kite" as alias` 导入另一个 Kite 文件，再用 `alias::symbol` 引用其中的函数或记录。路径相对于**写这条 `use` 的文件**，不是启动编译器时的工作目录；依赖文件中的 `use` 也按各自所在的目录解析。

`use` 必须放在其他声明或语句之前。被导入的文件只能在顶层写 `use`、`record`、`fn`（C 后端还允许 `extern c fn`）。把打印、赋值等可执行的顶层语句写在入口文件里。模块之间不能循环导入，例如 `a.kite` 导入 `b.kite`，而 `b.kite` 又导入 `a.kite`。

## 定义和使用记录

用 `record` 声明一个类型，每个缩进的 `字段名: 类型` 占一行。字段类型可以是 `number`、`string` 或另一个记录类型，包括 `geo::Point` 这样的限定名。用 `Name(参数...)` 构造记录：参数的数量、顺序和类型必须与字段声明一致。用 `.字段名` 读取字段，可以连写，例如 `marker.position.x`。

记录字段不可修改：`marker.position = new_position` 会报错。要更新记录，构造一条新记录再赋给变量。记录可以正常赋值，也可以作为函数参数或返回值。函数的参数类型写在 `:` 后，返回类型写在 `->` 后。

下面是一个完整示例。先在 [geo.kite](../examples/modules/geo.kite) 定义坐标和移动函数：

```kite
record Point
    x: number
    y: number

fn shift(point: Point, dx: number) -> Point
    ret Point(point.x + dx, point.y)
```

同目录中的 [main.kite](../examples/modules/main.kite) 导入并使用它：

```kite
use "geo.kite" as geo

record Marker
    label: string
    position: geo::Point

fn move(marker: Marker, dx: number) -> Marker
    ret Marker(marker.label, geo::shift(marker.position, dx))

start = geo::Point(2, 3)
marker = Marker("kite", start)
original = marker
marker = move(marker, 5)
p "{original.label}: ({original.position.x}, {original.position.y})"
p "{marker.label}: ({marker.position.x}, {marker.position.y})"
```

从仓库根目录编译和运行，任选一个后端：

```sh
# C（需要 GCC）
python kite/kite.py kite/examples/modules/main.kite --run

# JavaScript（需要 Node.js）
python kite/kite.py kite/examples/modules/main.kite --js
node kite/examples/modules/main.js

# Java（需要 JDK）
python kite/kite.py kite/examples/modules/main.kite --java
javac -encoding UTF-8 kite/examples/modules/Main.java
java -cp kite/examples/modules Main
```

三个后端的输出相同：

```text
kite: (2, 3)
kite: (7, 3)
```

也可以用 `python kite/kite.py kite/examples/modules/main.kite --unity` 生成 `Main.cs`，在 [Unity](unity.md) 中运行并查看 Console。

## 一维记录数组

用非空字面量 `[Point(1, 2), Point(3, 4)]` 创建记录数组，所有元素必须属于同一个记录类型；即使两个记录的字段完全相同，也不能混在一个数组里。函数接收记录数组时，显式写出 `Point[]` 参数类型；导入的类型写成 `geo::Point[]`：

```kite
use "geo.kite" as geo

fn move_first(points: geo::Point[], dx: number)
    first = points[1]
    points[1] = geo::Point(first.x + dx, first.y)

points = [geo::Point(2, 3), geo::Point(4, 5)]
move_first(points, 10)
points.push(geo::Point(6, 7))
rp point in points
    p "({point.x}, {point.y})"
```

输出：

```text
(12, 3)
(4, 5)
(6, 7)
```

- 下标从 **1** 开始，`points[-1]` 表示最后一项。`points[1] = geo::Point(...)` 替换整个元素；记录字段仍不可修改，`points[1].x = 10` 会报错。
- `len(points)` 读取长度；`points.push(...)` 向本地数组追加同类型的记录。函数参数借用调用者的数组，替换元素会影响调用者；函数内不能对数组参数 `push`。
- `copy = points[1..-1]` 复制数组，切片包含两端。替换副本元素或对副本 `push` 不影响原数组。不能写 `copy = points` 创建别名，也不能给数组变量整体重新赋值。
- 字面量 `[]` 不受支持。需要同类型的空数组时，用已有数组的空切片，例如 `empty = points[1..0]`，再对 `empty` 追加记录。
- `rp point in points` 按顺序遍历当前数组：循环中替换尚未访问的元素会影响后续访问，追加的元素也会继续被访问。循环变量代表本次取出的记录；请保证循环能结束。
- 不能直接 `p points`、把数组放进插值文本，或直接打印单条记录。用 `rp` 遍历，再打印记录的数字或文本字段。

数组只允许作为变量和函数参数，**任何数组都不能从函数返回，也不能作为记录字段**。记录数组只支持上述一维操作，不支持数组比较、`sort`、`join` 或记录矩阵。

完整可运行示例 [record_arrays.kite](../examples/modules/record_arrays.kite) 还展示了本地 `Marker[]` 参数、负下标赋值、切片独立性和遍历时追加元素。从仓库根目录运行：

```sh
python kite/kite.py kite/examples/modules/record_arrays.kite --run

python kite/kite.py kite/examples/modules/record_arrays.kite --js
node kite/examples/modules/record_arrays.js

python kite/kite.py kite/examples/modules/record_arrays.kite --java
javac -encoding UTF-8 kite/examples/modules/RecordArrays.java
java -cp kite/examples/modules RecordArrays

python kite/kite.py kite/examples/modules/record_arrays.kite --unity
```

Unity 生成的 `RecordArrays.cs` 可用于 [Unity](unity.md)，在 Console 查看输出。C、JavaScript、Java 和 Unity 的预期输出相同：

```text
point: 2
ends: 12, 4
copy: 12, 99; lengths: 2, 3
empty slice: 1, only
visit: a, 12
visit: changed, 20
visit: new, 40
length: 3
```

## 调用 C 外部函数

C 后端可以用 `extern c fn` 声明由宿主 C 代码实现的函数。显式写出参数类型和返回类型，在 `=` 后的字符串中指定要链接的 C 符号。当前只支持 `number` 参数和 `number` 返回值，均对应 C 的 `double`。C 实现必须与声明的签名一致。JavaScript、Java 和 Unity 后端不支持此声明。

例如，`program.kite`：

```kite
extern c fn scale(x: number) -> number = "host_scale"

p scale(7)
```

对应的 `helper.c`：

```c
double host_scale(double x) {
    return x * 3.0;
}
```

如两个文件都在当前目录，用 GCC 编译并运行，输出 `21`：

```sh
python kite.py program.kite --run --link helper.c
```

`--link` 可以重复指定，向 `--run` 或 `--exe` 的链接步骤传入 C 源文件、目标文件或静态库。与 `use` 不同，`--link` 的相对路径以运行命令的目录为准。也可以先用 `python kite.py program.kite` 生成 C 源文件，再用自己的 C 编译器编译，把宿主实现一起链接进去。
