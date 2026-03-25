# TODO

## 下一步

- [ ] 补 `main.py` 的 `systemd` service，完成应用本体开机自启收尾
- [ ] 做一次 `1~2` 小时的实机 soak test
- [ ] 实测并校准超声波空 / 满阈值
- [ ] 复测最近的 MJPEG 首次加载重连逻辑，确认长时间运行下不再需要手动刷新

## 前端收尾

- [ ] 如果当前 `Cards & Access` 还不够顺手，补直接编辑卡权限 / 时间窗的 UI
- [ ] 把仍然需要人工改 `config.py` 的少量设备校准项，评估是否迁到 `Settings`

## 可选项

- [ ] 如果 `PN532 + I2C` 长时间运行还有异常，再评估切到 `SPI`
- [ ] 评估是否把视频链路从 `MJPEG` 升级到 `H.264` / `WebRTC`
- [ ] 评估是否接入 Cloudflare Tunnel 做外网访问
- [ ] 仅在业务明确需要时，再补“door event 触发的人脸 search 分支”

## 已完成

### 核心硬件与后端

- [x] RFID 读卡、卡录入、权限校验
- [x] 门锁舵机开关门与自动关门
- [x] CSI 摄像头视频流、手动抓拍、RFID 抓拍、按钮抓拍、人脸近距离抓拍
- [x] 人脸检测、前端叠框、云台追踪、standby、丢脸后 search 恢复
- [x] 超声波占用检测
- [x] SQLite 事件存储与结构化表快照
- [x] 快照文件上限清理、启动对账、运行时对账、删文件同步删库
- [x] 按钮邮件通知、邮件方案管理、测试邮件
- [x] 本地 buzzer / LED 状态联动
- [x] 未授权刷卡、按钮连按、重复未授权的本地告警规则

### 前端操作台

- [x] `Overview / Cards & Access / Events & Snapshots / Debug / Data / Settings` 信息架构
- [x] `Tabler` 只作骨架和组件参考，业务代码继续收敛在 `frontend/`
- [x] 超长单文件前端已拆到 `frontend/styles/` 和 `frontend/scripts/`
- [x] 右上角全局工具区：主题切换、通知铃铛、profile
- [x] 本地 `Profile Settings`
- [x] 头像上传、重置、后端持久化、`Display Name -> initials` 回退
- [x] `Notification Settings` 分层：前端铃铛偏好 + 设备邮件方案
- [x] 深色模式
- [x] 快照查看 modal、键盘切图、缺图兜底
- [x] 树莓派运行状态卡：温度、CPU、内存、程序运行时长等
- [x] `Debug / Data` 表展示与“最新 N 行”筛选

### 运行与配置

- [x] 统一配置入口 `config.py`
- [x] 统一数据目录 `data/`
- [x] Raspberry Pi 运行基线、依赖安装方式、硬件 smoke test 路径
- [x] 设备级 profile / email settings API
- [x] 业务测试清单和 5 分钟 demo runbook

## 已明确不做

- [x] 多用户账号
- [x] 登录 / 注册 / 注销
- [x] 人脸身份识别
- [x] PIR 传感器方案
- [x] 把 `Tabler` 源码本身当作业务前端目录

## 备注

- [x] 当前前端定位是“单设备测试 / 运维操作台”，不是最终展示站点
- [x] 当前系统按单设备部署设计
