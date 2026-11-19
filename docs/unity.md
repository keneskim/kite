# 用 kite 写 Unity 游戏

kite 可以把游戏逻辑翻译成 **Unity 的 C# 脚本**。

```
python3 kite.py 游戏.kite --unity
→ 生成 游戏.cs
```

把这个 `.cs` 丢进 Unity 项目的 `Assets/`，再拖到一个方块上就行。

> 类名和文件名会自动对齐（Unity 强制要求），不用自己改。

---

## 写法：两个函数

```
fn start()
    p "游戏开始"

fn update()
    if key("left")
        move_x(-6)
    if key("right")
        move_x(6)
    if key("space") && on_ground()
        jump(11)
```

- `start()`：游戏开始时跑一次
- `update()`：每一帧跑一次（**游戏逻辑都写这里**）

顶层代码也会放进 Start。

---

## 能用的内置函数

| 写法 | 作用 |
|---|---|
| `key("left")` | 按住左键返回 1，否则 0 |
| `key("right")` / `"up"` / `"down"` / `"space"` / `"a"` `"d"` `"w"` `"s"` | 同上 |
| `move_x(6)` | 把横向速度设成 6（负数往左） |
| `jump(11)` | 把纵向速度设成 11（往上，负数往下） |
| `on_ground()` | 踩在地上返回 1，空中 0 |
| `x()` / `y()` | 当前坐标 |
| `set_pos(x, y)` | 直接传送到某个位置 |
| `p 值` | 输出到 Unity 的 Console |
| `txt` `num` `len` `up` `low` `trim` | 文本处理 |

其余语言功能照常用：`if` `rp` 函数、`+` 拼接、字符串插值。

---

## 一个完整的跳跃脚本

```
fn update()
    # 左右跑
    if key("left")
        move_x(-6)
    if key("right")
        move_x(6)

    # 跳
    if key("space") && on_ground()
        jump(11)

    # 掉出世界就拉回来
    if y() < -10
        set_pos(0, 2)
        p "掉下去了"
```

---

## 挂到 Unity 里

1. 建一个 2D 项目，放一个方块当玩家
2. 方块上要有 **Rigidbody 2D**（Gravity Scale 3，勾 Freeze Rotation Z）和 **Box Collider 2D**
3. 地面也要有 **Box Collider 2D**
4. 把生成的 `.cs` 拖进 `Assets/`，再拖到玩家方块上
5. 点 Play

手感参数（速度 6、跳跃 11）直接改 `.kite` 里那两个数，重新生成就行。

---

## Unity 版暂时不支持

- 数字和文本数组；一维[记录数组](modules.md#一维记录数组)已支持字面量、下标读写、`push`、切片、`len`、`rp` 和函数参数
- 文件和网络（`read` `write` `serve`）
- 二维表（`mat`）

用到会直接报错，并列出能用的函数名——不会悄悄生成坏代码。

```
出错了：没有叫「now」的函数（Unity 版只有 jump、key、len、low、move_x、num、on_ground、set_pos、trim、txt、up、x、y）
```

---

## 验证到什么程度

生成的 C# 会在测试里用一套 **假的 UnityEngine 桩**（`tests/UnityStub.cs`）编译一遍，保证语法和类型没问题。

但**没有在真的 Unity 里跑过**——我这边没有 Unity。如果挂上去报错，把红字发我。
