# 第一次开机：30 分钟做出能跳的方块

目标：一个方块，能用 ← → 跑、空格跳，相机跟着走。
**不用读完代码**，只要会点鼠标和拖组件。

---

## 1. 建项目（3 分钟）

- Unity Hub → New project → **2D**（Built-in Render Pipeline）
- 名字随便，比如 `PlatformerFirst` → Create

## 2. 摆两个方块（5 分钟）

**地面**
- Hierarchy 空白处右键 → 2D Object → Sprites → **Square**
- 改名 `Ground`
- Inspector 里 Transform：Position `(0, -3, 0)`，Scale `(20, 1, 1)`
- 加组件：**Add Component → Box Collider 2D**

**玩家**
- 再建一个 Square，改名 `Player`
- Position `(0, 0, 0)`，Scale `(1, 1, 1)`
- 加组件：
  - **Rigidbody 2D** → Gravity Scale 改成 `3` → Constraints 勾上 **Freeze Rotation Z**
  - **Box Collider 2D**

> 没有 Rigidbody 不会掉，没有 Collider 会穿地——这两个漏一个都不行。

## 3. 用 kite 生成脚本（5 分钟）

在手机/终端里：

```
python3 kite.py unity/game.kite --unity
```

会生成 `unity/Game.cs`。**把这个文件发到电脑上，拖进 Unity 的 `Assets/` 文件夹**，
再把 Assets 里的 `Game` 拖到 Hierarchy 的 **Player** 上。

（`PlayerController.cs` 是同一份逻辑的手写版，不想用 kite 生成时可以直接粘它。）

相机：新建 `CameraFollow` 脚本，粘 `CameraFollow.cs`，拖到 **Main Camera** 上，
再把 **Player** 拖进 Inspector 里 `Camera Follow` 的 **Target** 格子。

## 4. 玩（2 分钟）

点顶部 ▶ Play，用 **← →** 移动、**空格** 跳。

---

## 调手感（这是你的活）

选中 Player，在 Inspector 的 Player Controller 里改：

| 参数 | 作用 | 试试 |
|---|---|---|
| Move Speed | 跑多快 | 4 太慢、10 太快，找 6~8 |
| Jump Force | 跳多高 | 11 大约跳一个方块高，13 跳两个 |

**这就是"游戏手感"的真正来源。** 同一个脚本，参数不同就是两个游戏。

---

## 卡住了看这里

| 现象 | 原因 |
|---|---|
| 方块不动 | Player 上没拖 PlayerController |
| 方块往下掉不停 | Ground 没加 Box Collider 2D |
| 跳不起来 | Player 没加 Rigidbody 2D，或 Collider 没加 |
| 相机不动 | CameraFollow 的 Target 没设 |
| 报错 `velocity` 已过时 | Unity 6 里把它换成 `linearVelocity`，两处 |
| 方块自己转 | Rigidbody 2D 的 Freeze Rotation Z 没勾 |

> 这两个脚本是照 Unity 标准写法写的，但**没在真 Unity 里跑过**（我这边只有手机）。
> 第一次打开如果有报错，把红字发我，一般一两行就能修。
