# Frontend Notes

当前前端仍然是“单设备调试操作台”，不引入新的构建链，也不把 `Tabler` 整体搬进来。这里的目标是保留原生 `HTML + CSS + JS` 的低门槛，同时把结构拆清楚，后续加 `dark mode`、通知铃铛、profile、登录页时不再回到一个超长单文件里摸索。

## Directory Map

- `index.html`
  - 只保留页面结构、视图容器和少量页面级内联布局。
  - 当前入口仍然是单页，侧栏切换 `Overview / Cards / Events / Debug`。
- `styles/theme.css`
  - 主题变量、背景、全局字体和基础色板。
  - 未来做 `dark mode` 时，优先在这里加 `data-theme="dark"` 对应变量。
- `styles/layout.css`
  - 页面骨架：侧栏、工作区、主栅格、响应式断点。
  - 如果后面增加 topbar、profile 页面容器、auth 页面壳子，优先放这里。
- `styles/components.css`
  - 面板、卡片、按钮、表格、toast、视频叠加区等组件样式。
  - 视觉微调大多会落在这里。
- `scripts/dom.js`
  - 所有当前页面依赖的 DOM 引用和 canvas context。
- `scripts/state.js`
  - 前端运行时状态和轮询 / WebSocket 常量。
- `scripts/formatters.js`
  - 时间、标签、状态文本、人类可读化等纯函数。
- `scripts/renderers.js`
  - 负责把状态渲染到页面上，也包括视频框 overlay 绘制。
- `scripts/api.js`
  - `fetchJson`、各个后端接口调用、页面刷新动作。
- `scripts/app.js`
  - 应用入口、事件绑定、WebSocket、轮询、页面 bootstrap。

## Current Rules

- 保持“无前端框架、无构建链”前提，文件直接被 FastAPI 静态托管。
- 优先把新功能加进现有模块，不要把逻辑重新塞回 `index.html`。
- 如果只是改展示文案或区块结构，优先动 `index.html`。
- 如果是主题、阴影、卡片视觉、topbar 样式，优先动 `styles/`。
- 如果是接口调用、轮询、WebSocket、通知逻辑，优先动 `scripts/`。

## Planned UI Extensions

- 右上角全局工具区：
  - `dark mode` 开关
  - 通知铃铛
  - profile 入口
- profile / settings：
  - 个人信息
  - 邮件通知设置
  - 登出
- auth 页面：
  - 后续若需要，建议单独补登录页，不和当前调试台首页混在一起。

## Tabler Usage Boundary

- `Tabler` 目前只作为骨架、组件层次和交互动效参考。
- 不直接复制整套模板文件结构。
- 需要参考时，优先借鉴：
  - topbar 工具区
  - avatar / profile dropdown
  - theme toggle
  - card 层次和列表信息密度
