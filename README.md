# 三维场景创作平台（v0.1 · 场景层级编辑）

React + three.js 前端、Python/FastAPI 后端的可编辑三维场景平台。第一版聚焦**场景层级编辑**：
后续版本在此数据模型上扩展材质、灯光和动画。

## 功能

- 添加基础物体（立方体/球体/圆柱/圆锥/平面）与空组
- 树形层级面板：折叠、重命名、成组、删除、整组复制
- 拖拽换组：把节点拖到任意组上，或拖到空白处移到根级
- **换组时可选择“保持眼前位置”**：前端与后端都按
  `新局部矩阵 = inverse(新父级世界矩阵) × 当前世界矩阵` 重新计算局部 TRS
  （three.js `Object3D.attach` 同一约定；Euler 顺序 XYZ）
- 3D 视口：轨道相机、平移/旋转/缩放 gizmo（W/E/R），点击拾取
- 多步撤销/重做（Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z），撤销重做时恢复选择
- **保存的是可继续编辑的场景图 JSON**（扁平节点表 + 显式父子链接），不是截图；
  重新载入后父子关系、局部变换完整恢复
- 复制整组为深拷贝，所有父子关系保留
- 循环挂接（挂到自己/子孙下）在前端和后端都会被拦截，失败操作不入历史
- 页内“前后端最终位置一致性校验”按钮：逐节点比对页面 three.js 矩阵与后端矩阵

### 关于非均匀缩放

当祖先链含非均匀缩放且中间有旋转时，`inverse(parent) × world` 会产生剪切，
而纯 TRS（无剪切）无法无损表达——这是 three.js `Object3D.attach` 同样的固有限制。
均匀缩放链下世界位姿可精确保留（后端有 1e-9 级测试）；非均匀夹具用于前后端
**计算结果一致性**互校（同一文档两边算出的矩阵相同）。

## 目录

```
backend/
  scene_math.py       # 列主序 4x4：compose/decompose/invert/乘法（对齐 three.js 内存布局）
  scene_model.py      # 场景文档：校验、循环检测、世界矩阵、换组重算、成组、复制、删除
  storage.py          # 原子写入的 JSON 文件持久化
  main.py             # FastAPI 路由（含 /api/compute/world 无状态计算）
  generate_fixtures.py# 生成前后端共享的金标夹具
  seed_demo.py        # 写入一个深嵌套演示场景 scenes/demo.json
  fixtures/           # 金标 JSON（深嵌套+旋转缩放、换组后状态），供 vitest 互校
  tests/              # pytest：数学/场景图/HTTP API（ASGI 直连，无需网络）
frontend/
  src/sceneOps.ts     # 与后端同构的场景逻辑（基于 three.js 数学）
  src/store.ts        # zustand：文档快照历史（撤销/重做）、实时拖动编辑
  src/components/     # Viewport / HierarchyTree / Inspector / Toolbar / ConsistencyPanel
  test/               # vitest：金标矩阵互校、换组保位、循环拦截、撤销、复制
```

## 启动

```bash
# 后端（默认存到 ./scenes）
.venv/bin/python -m pip install -r requirements.txt   # 首次
.venv/bin/python -m backend.seed_demo                 # 可选：写入演示场景
.venv/bin/python -m uvicorn backend.main:app --port 8000

# 前端开发服务器（/api 已代理到 8000）
cd frontend && npm install && npm run dev             # http://localhost:5173

# 或构建后由后端单端口托管
cd frontend && npm run build
# 然后访问 http://localhost:8000/
```

## 测试

```bash
.venv/bin/python -m pytest backend/tests -q           # 16 个后端测试
cd frontend && npx vitest run                         # 12 个前端测试
cd frontend && npx tsc --noEmit                       # 类型检查
```

共享金标夹具改动后重新生成：`.venv/bin/python -m backend.generate_fixtures`

## HTTP API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/scenes` | 列出场景 id |
| POST | `/api/scenes/{id}` | 创建（空 body 为空场景） |
| GET/PUT | `/api/scenes/{id}/doc` | 读取/整体保存可编辑场景图 |
| POST | `/api/scenes/{id}/nodes` | 添加节点 |
| PUT | `/api/scenes/{id}/nodes/{nid}/transform` `/rename` | 改变换/名称 |
| POST | `/api/scenes/{id}/reparent` | 换组，`preserveWorld` 控制是否重算局部位姿 |
| POST | `/api/scenes/{id}/group` | 同级节点成组 |
| POST | `/api/scenes/{id}/nodes/{nid}/duplicate` | 深拷贝整组 |
| DELETE | `/api/scenes/{id}/nodes/{nid}` | 删除子树 |
| GET | `/api/scenes/{id}/world` | 后端计算最终世界 TRS+矩阵 |
| POST | `/api/compute/world` | 对任意文档无状态计算世界矩阵（校验用） |
