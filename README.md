# 受限代数表达式等价复核

飞控规程团队在替换控制表达式前，用本系统确认候选式**能否由已批准的代数
重写规则推出**——而非凭输入样例猜测等价。系统对等式规则做饱和重写与
同余闭包，只有在规则**饱和后**才作出等价判断。

## 能力与规则

- 两个受限表达式 + 至多 **20** 条带变量等式规则；
- 表达式仅含**具名常量**与**一元 / 二元函数调用**，如 `f(a, g(b, c))`；
- 规则变量以 `?` 前缀书写（如 `?x`），规则中也可出现具名常量
  （如 `a = b`、`add(ZERO, ?x) = ?x`）；
- 规则**右侧不得引入左侧未出现的变量**；
- 任一推导项不得超过声明的 **80 个节点**；
- 结论四态：`equivalent`（等价）、`inequivalent`（不等价）、
  `incomplete`（未完成）、`invalid`（无效）。

判定语义：

| 情形 | 结论 |
|---|---|
| 规则应用队列全部排空（饱和），两式在同一等价类 | 等价，逐步展开规则实例与同余依据 |
| 已饱和但分属不同等价类 | 不等价，仅给哈希一致的稳定摘要，**清除旧证据** |
| 达到节点上限或规则应用次数上限前仍未饱和 | **未完成**，不得作等价判断 |
| 语法错误、查询含未绑定变量、超限规则 / 表达式 | **无效**，**清除旧结论** |

## 实现要点

- `app/lexer.py`、`app/parser.py`：受限语法的词法 / 递归下降解析，
  AST 为哈希一致的不可变 `Term`；
- `app/engine.py`：结构哈希归一（interning）的项林 + 并查集等价类 +
  Nelson–Oppen 风格同余闭包；规则双向一阶匹配，实例进入确定顺序的
  FIFO 待合并队列与待重建（枚举）队列；每次成功合并都保留“规则实例”
  或“同余”证据，等价时在证据图上做确定性 BFS 并嵌套展开；
- `app/service.py`：请求校验、规范摘要与四态结论装配（无状态）；
- `app/server.py`：零第三方依赖 HTTP 服务
  （`GET /` 页面、`GET /health` 健康响应、`POST /api/verify` 真实接口）；
- `app/webui.py`：内联 CSS/JS 的单页界面。

## 本地运行（无需 Docker）

```bash
python3 -m app.server            # 默认 0.0.0.0:8080
PORT=9090 python3 -m app.server  # 自定义端口
python3 -m unittest discover -s tests
python3 scripts/verify           # 一次性验收（无 Web 时自动跳过 HTTP 冒烟）
```

## Docker Compose

```bash
docker compose up --build           # 启动 Web 与一次性验收服务
docker compose up verify            # 仅运行验收（依赖 web 健康后启动）
HOST_PORT=9090 docker compose up    # 可配置宿主端口（默认 8080）
```

- `web`：常驻页面 / 健康 / 接口服务，带健康检查；
- `verify`：名为 **verify** 的**一次性**可执行验收服务，执行后退出，
  以退出码报告结果（0 通过 / 1 失败），`restart: "no"`。

验收脚本依次穿插执行：构建检查（字节码编译、模块导入）→ 代码测试
（unittest）→ 接口冒烟（交换律等价推导、饱和后非等价、资源受限未完成、
无效录入）→ HTTP 冒烟（健康响应、页面、`/api/verify` 四态）。

## 接口示例

```bash
curl -s -X POST localhost:8080/api/verify \
  -H 'Content-Type: application/json' \
  -d '{"left":"h(f(a,b))","right":"h(f(b,a))",
       "rules":["f(?x, ?y) = f(?y, ?x)"]}'
```

返回 `equivalent`，推导中外层 `h(...)` 的合并标注为**同余**依据，
内层参数对嵌套给出交换律的**规则实例**与变量绑定
（`?x ↦ a`、`?y ↦ b`）。
