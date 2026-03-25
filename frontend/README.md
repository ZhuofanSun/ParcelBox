# Frontend Notes

当前前端仍然是“单设备调试操作台”，不引入新的构建链，也不把 `Tabler` 整体搬进来。这里的目标是保留原生 `HTML + CSS + JS` 的低门槛，同时把结构拆清楚，后续加 `dark mode`、通知铃铛、profile、设备级设置页时不再回到一个超长单文件里摸索。

## Directory Map

- `index.html`
  - 只保留页面结构、视图容器和少量页面级内联布局。
  - 当前入口仍然是单页，侧栏切换 `Overview / Cards / Events / Debug`，profile 菜单还可以打开独立的 `Settings` 视图。
- `styles/theme.css`
  - 主题变量、背景、全局字体和基础色板。
  - 未来做 `dark mode` 时，优先在这里加 `data-theme="dark"` 对应变量。
- `styles/layout.css`
  - 页面骨架：侧栏、工作区、主栅格、响应式断点。
  - 如果后面增加 topbar、profile 页面容器、settings 页面壳子，优先放这里。
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

## Header Tools

- 右上角全局工具区已经接入：
  - `dark mode` 开关，主题选择写入 `localStorage`
  - 通知铃铛，当前只展示高价值提醒：按钮按下、未授权刷卡、近距离人脸触发
  - profile trigger，下拉菜单承接后续设备设置入口

## Settings View

- 已接入一个本地 settings 视图，通过 profile dropdown 进入。
- 当前可配置：
  - 控制台显示名称
  - 角色 / 副标题文案
  - 主题偏好
  - 头像上传 / 重置
  - `Display Name -> initials` 默认头像
  - 通知铃铛里三类提醒的开关
- 主题和铃铛筛选仍写浏览器本地存储。
- profile 名称、角色和头像现在走后端设备级持久化。

## Planned UI Extensions

- profile / settings：
  - 设备级 profile 页面和更完整的本机设置
  - 邮件通知设置和后端设置接口
  - 后端持久化头像和邮件订阅方案

## Tabler Usage Boundary

- `Tabler` 目前只作为骨架、组件层次和交互动效参考。
- 不直接复制整套模板文件结构。
- 需要参考时，优先借鉴：
  - topbar 工具区
  - avatar / profile dropdown
  - theme toggle
  - card 层次和列表信息密度
