# 跨后端回归测试

在仓库根目录运行（只需要 Python 3.8+ 标准库）：

```sh
python kite/tests/run.py
```

也可在 `kite/` 下运行 `python tests/run.py`。入口与当前工作目录无关。
Linux/macOS 通常使用 `python3`。原 `sh tests/run.sh`、`js.sh`、`java.sh`、
`unity.sh` 和 `web.sh` 均包装同一个 Python 入口，可通过 `PYTHON` 指定解释器。

默认检测并测试可用后端：

- C：Linux/macOS 使用 PATH 中的 `gcc`；Windows 优先使用已加载环境中的
  `cl`，否则使用 `gcc`。MSVC 使用 `/utf-8 /std:c11` 并链接 `ws2_32.lib`。
  在 **x64 Native Tools Command Prompt for VS** 中运行即可；入口不会修改或加载开发者环境。
- JavaScript：需要 `node`。
- Java：需要 `javac` 和 `java`，源码和进程输入输出显式使用 UTF-8。
- Unity：始终测试生成和 KiteError；有 .NET SDK、`csc` 或 `mcs` 时，使用
  `UnityStub.cs` 编译游戏及文本/循环用例。有 .NET、Windows C# 可执行环境或 Mono
  时，通过 `UnityConsole.cs` 调用 `Start` 并核对输出；运行时设置 `fr-FR`，
  确保数字格式不受本机小数逗号文化影响。无 C# 工具时明确报告 SKIP。
- Web：有 C 编译器时编译现有网页示例，用临时本地端口请求 `?km=10`，
  检查 HTTP 200、正常换算 HTML 及服务器 stdout/stderr，最后停止服务器。

默认缺少工具的后端为 SKIP；显式指定缺少工具的 C/JS/Java/Web 后端则失败。
Unity 的 C# 编译与运行始终可选，缺工具会显示 SKIP，且不会把仅生成计为完整通过。
用例失败或筛选结果没有通过项时退出 1，成功退出 0。

```sh
# 指定一个或多个后端（显式指定时要求工具存在）
python kite/tests/run.py --backend c --backend js --backend java

# 原 13 例之外的重点回归
python kite/tests/run.py --case unicode --case format --case num --case loop_dynamic --case array_copy

# 单独跑负例：非法 num、数组/矩阵/矩阵行别名，以及 KiteError
python kite/tests/run.py --backend js --case 'num_*' --case '*alias' --case kite_error

# 记录数组：同一示例在 C、JS、Java 和 Unity stub 上运行，另检查编译期负例
python kite/tests/run.py --case 'record_array*' --case number_array_return

# 单独跑 Unity 或 Web；提高慢机器的单步骤超时
python kite/tests/run.py --backend unity --timeout 60
python kite/tests/run.py --backend web
```

原有 13 个顶层 `.kite/.out` 用例及其 `.in` 输入均被保留。
`bounds` 明确要求运行退出 1、stdout 为空、stderr 与原期望一致。
新增正例放在 `cases/`，由 C、Node、Java 统一运行：

- `unicode`：中文、补充平面字符、组合字符、ZWJ 序列，按 code point 计算
  `len/find/sub` 及 1-based inclusive 正/负索引切片。
- `format`：15 位有效数字、科学计数法、指数无 `+`/前导零、负零，
  同时覆盖打印、`txt`、插值、数组和 `join`。
- `num`：空串、ASCII 空白、严格十进制、指数、小数、下溢到零。
- `loop_dynamic`：动态降序/升序范围、端点调用一次且按顺序、范围和次数快照、
  零次/负次数以及相同端点。
- `array_copy`：普通数组、字符串数组和矩阵行用显式切片复制后单独修改/push。
- `unity_text`：Unity 支持子集的 Unicode、num 和一致格式，也在三个控制台后端运行。
- `record_arrays`：直接运行 `examples/modules/record_arrays.kite`，覆盖本地和模块限定的
  `Record[]` 参数、正/负下标、元素替换、借用参数修改、追加、独立切片、空切片、长度和动态遍历；
  C、JS、Java 和 Unity stub 逐字核对相同输出。
- `record_array_*` / `number_array_return` 负例：元素/参数类型错误、数组别名、借用参数追加、
  返回数组、数组字段、直接打印/插值、记录字段修改、数组比较、排序、拼接、记录矩阵和空字面量。

负例内嵌在入口中，分别验证完整退出码和独立 stdout/stderr；非法数字必须携带
Kite 第 2 行错误并保留错误发生前的 `before` 输出，后续 `after` 不得执行。
编译期负例要求 KiteError 诊断、准确行号和源码片段，且不生成目标文件。

每次运行使用自动清理的系统临时目录：复制输入后调用真实 CLI，生成 C/JS/Java/C#、
对象文件、可执行文件、PDB、class、.NET 项目和缓存均位于该目录。运行程序也在临时目录内，
不会把产物写到源码树。Python 禁止生成 pycache；.NET 包源清空，不需要下载依赖。

比较时严格用 UTF-8 解码，只有 CRLF/CR 转成 LF，不裁剪空格或末尾换行。
逐个断言转译/编译/运行退出码，转译 stdout/stderr，程序独立 stdout/stderr。
编译器可输出正常构建信息。所有外部步骤和 HTTP 请求都有超时（默认 30 秒）。
