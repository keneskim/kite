# 模块、记录与 C 外部函数

## 导入模块

在文件开头写 `use "path.kite"`。模块中的函数和记录会直接出现在当前文件里，不需要别名，也不需要 `::`。

```kite
use "geo.kite"

point = Point(2, 3)
moved = shift(point, 5)
p moved.x
```

路径相对于**写这条 `use` 的文件**。依赖文件里的 `use` 也按各自所在目录解析。`use` 必须放在其他声明和语句之前。

被导入的文件只能包含 `use`、`record` 和 `fn`；C 后端还允许 `extern`。把打印、赋值等可执行语句写在入口文件里。模块之间不能循环导入。

如果两个模块导出同名声明，或者导入的名字和本文件声明冲突，编译器会报错。

## 定义和使用记录

一行就能定义一个记录：

```kite
record Point(x: number, y: number)
```

字段类型可以是 `number`、`string` 或另一个记录。用 `Point(2, 3)` 构造，用 `.x` 读取字段，也可以连写，例如 `marker.position.x`。

记录字段不可修改。要更新，构造一条新记录：

```kite
point = Point(point.x + 1, point.y)
```

记录可以作为函数参数和返回值。函数的参数和返回类型通常可以推断，只在需要时标注。

## 一个完整模块

先在 `geo.kite` 中定义坐标和移动函数：

```kite
record Point(x: number, y: number)

fn shift(point, dx)
    ret Point(point.x + dx, point.y)
```

在 `main.kite` 中直接使用导入的名字：

```kite
use "geo.kite"

record Marker(label: string, position: Point)

fn move(marker, dx)
    ret Marker(marker.label, shift(marker.position, dx))

start = Point(2, 3)
marker = Marker("kite", start)
original = marker
marker = move(marker, 5)
p "{original.label}: ({original.position.x}, {original.position.y})"
p "{marker.label}: ({marker.position.x}, {marker.position.y})"
```

从仓库根目录运行：

```sh
python kite.py examples/modules/main.kite --run
```

也可以生成其他后端：

```sh
python kite.py examples/modules/main.kite --js
node examples/modules/main.js

python kite.py examples/modules/main.kite --java
javac -encoding UTF-8 examples/modules/Main.java
java -cp examples/modules Main
```

输出：

```text
kite: (2, 3)
kite: (7, 3)
```

## 一维记录数组

用非空字面量创建记录数组：

```kite
points = [Point(2, 3), Point(4, 5)]
points.push(Point(6, 7))
```

所有元素必须属于同一个记录类型。函数接收记录数组时，通常不用写类型；需要显式标注时写 `Point[]`，导入的类型同样直接写 `Point[]`。

```kite
fn move_first(points, dx)
    first = points[1]
    points[1] = Point(first.x + dx, first.y)

points = [Point(2, 3)]
move_first(points, 10)
```

- 下标从 **1** 开始，`points[-1]` 表示最后一项。
- `points[1] = Point(...)` 替换整个元素；记录字段仍不可直接修改。
- `len(points)` 读取长度；`points.push(...)` 向本地数组追加记录。
- `copy = points[1..-1]` 复制数组，切片包含两端。替换副本元素或对副本 `push` 不影响原数组。
- 不能写 `copy = points` 创建别名，也不能给数组变量整体重新赋值。
- 没有空数组字面量 `[]`。需要空数组时，用已有数组的空切片，例如 `empty = points[1..0]`。
- `rp point in points` 按顺序遍历当前数组；循环中替换尚未访问的元素会影响后续访问，追加的元素也会继续被访问。
- 不能直接打印数组或记录，也不能把数组放进插值。遍历后打印字段。
- 不支持数组比较、`sort`、`join`、记录矩阵，也不能从函数返回数组或把数组放进记录字段。

完整示例见 [record_arrays.kite](../examples/modules/record_arrays.kite)。

## 调用 C 外部函数

C 后端可以声明由宿主 C 代码实现的函数。函数名就是 C 符号名：

```kite
extern host_scale(x: number) -> number

p host_scale(7)
```

```c
double host_scale(double x) {
    return x * 3.0;
}
```

编译并链接：

```sh
python kite.py program.kite --run --link helper.c
```

`--link` 可以重复，接受 C 源文件、目标文件或静态库，只用于 `--run` 或 `--exe`。

目前只支持 `number` 参数和 `number` 返回值，对应 C 的 `double`。宿主实现必须匹配声明。JavaScript、Java 和 Unity 后端不支持 `extern`。
