# 三维场景创作平台（第一版：场景层级编辑）

React + TypeScript + three.js 前端，FastAPI + NumPy 后端。保存的是**可继续编辑的场景
JSON 文档**（节点 + 父子关系 + TRS），不是截图；后续材质、灯光、动画都挂在同一套节点
模型上扩展。

## 功能

- 加入基础物体：立方体、球体、圆柱、圆锥、平面（可直接建在选中组内）
- 成组：把选中节点包进新组，自动取其世界变换，**眼前位置不变**
- 层级树拖拽换组：拖到另一个组，或拖到底部区域移到场景根层级
  - 选「保持眼前位置」：后台按新父级的旋转/缩放反算局部 TRS
  - 选「保留局部数值」：局部数值不变、世界位置随父级变化
- 循环挂接拦截：不能把组挂到自己或自己的后代下（后端 400，界面提示）
- 复制整个组：深拷贝整棵子树，父子关系完整保留
- 可复用装配件：选中普通组可制作装配件，并多次放入实例
  - 实例根节点保留各自父级、位置、旋转和缩放
  - 内部零件支持按实例覆盖 TRS；修改原件会重新生成仍链接的实例，并保留实例覆盖
  - “脱离原件”会把实例转成普通节点；保存重载后不会重新绑定
  - “删除原件”会保留并自动脱离所有现有实例，不会悄悄删除场景内容
- 多步撤销 / 重做（最多 100 步，Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z）
- 删除整棵子树；检查器里改位置 / XYZ 欧拉旋转 / 缩放
- 保存 / 新建 / 重新载入：JSON 落盘，重载后父子关系与变换完全恢复
- 检查器实时显示后端算出的世界位置 / 旋转 / 缩放

## 矩阵一致性

后端 backend/transforms.py 逐行对照 three.js 的列主序 Matrix4（compose / decompose
/ Quaternion / Euler XYZ），序列化的 16 元素矩阵与 THREE.Matrix4.elements 同序。
shared/check-three.mjs 用真实 three.js 对层层嵌套、带旋转缩放的场景（A 组旋转 90°Z+
缩放 2 → B 立方体旋转 90°Y+非均匀缩放 → C 球体）逐元素核对，最大误差约 1e-15。
前端视口与后端使用同一份场景文档各自计算世界矩阵，检查器展示后端结果。

## 运行

    ./run-dev.sh
    # 或分别启动：
    #   SCENE_STORE_DIR=runtime/scenes python3 -m uvicorn backend.app:app --port 8000
    #   cd frontend && npm install && npm run dev

打开 http://127.0.0.1:5173 。场景文件保存在 runtime/scenes/<id>.json。

## 测试

    # 后端：纯逻辑 + ASGI 端到端（建物体/换组/循环拦截/复制组/成组/装配件/保存重载）
    python3 -m pytest backend/tests -q

    # 前端：three.js 重建世界矩阵与后端导出逐元素一致 + 换组数学
    cd frontend && npx vitest run

    # 真实 three.js 数值核对
    cd frontend && node ../shared/check-three.mjs

## 结构

    backend/
      transforms.py   # 与 three.js 对齐的 TRS / 四元数 / 欧拉
      scene_ops.py    # 增删、成组、换组（保位置）、复制组、世界矩阵
      models.py       # 场景文档 Pydantic 模型
      storage.py      # JSON 持久化
      app.py          # FastAPI（操作无状态：入参场景 -> 返回新场景）
    frontend/src/
      lib/store.ts    # zustand：场景状态 + 100 步撤销/重做 + API
      components/     # Viewport(three.js) / HierarchyTree(拖拽) / Inspector / Toolbar
    shared/
      nested-world.example.json  # 嵌套场景的后端世界矩阵基准
      check-three.mjs            # three.js vs 后端逐元素比对
