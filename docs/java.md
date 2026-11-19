# Java 后端

```
python3 kite.py 程序.kite --java
→ 生成 程序.java
```

```
javac -encoding UTF-8 程序.java
java 程序
```

> 类名会按文件名自动改成首字母大写（`hello.kite` → `Hello.java` / `class Hello`），
> 因为 Java 要求文件名和 public 类名一致。

需要 Java 11 以上（用到了 `String.repeat`）。

---

## 和 C 版的关系

回归测试在 C 和 Java 上使用同一份预期输出，涵盖：

- 中文输入输出
- `seed(7)` 的随机序列（用 `Long.remainderUnsigned` 复刻了 C 的 64 位无符号取模）
- 越界报错文案
- 二维表、切片、`push`

---

## 内部怎么表示的

用户看不到，但知道一下有好处：

| kite | Java |
|---|---|
| 数字 | `double` |
| 文本 | `String` |
| 数组 | `ArrayList<Double>` / `ArrayList<String>` |
| 二维表 | `ArrayList<ArrayList<Double>>` |
| `xs.len` | `xs.size()` |
| `xs.push(1)` | `xs.add(1)` |
| `"a" == "b"` | `a.equals(b)`（Java 的 `==` 比引用，不能直接用） |

所以生成的代码比 C 版干净——不用管内存，也不用写字符串运行时。

---

## 不支持

| 不支持 | 原因 |
|---|---|
| `serve` / `form` / `html` | 那是 C 后端的本地 HTTP 服务 |

其他都能用：文件读写、`ask`、随机数、二维表、切片。

---

## 测试

```
python3 tests/run.py --backend java
```

把每个测试程序编译成 Java、用 javac 编译、跑一遍，和 C 版的期望输出逐字比对。
