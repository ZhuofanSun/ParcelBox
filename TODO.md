# TODO

## 已确认信息

### 项目级共识

- [x] 项目平台：树莓派。
- [x] 项目场景：模拟快递柜 / 智能柜的使用流程。
- [x] 当前已有接线与原型资料：
  - [x] `IOT-project/wire.pdf`
  - [x] `IOT-project/wire_schem.pdf`
  - [x] `IOT-project/wire.fzz`
- [x] dashboard 会提供状态查看能力。
- [x] dashboard 会提供主动控制能力，已明确包含“开门 / 关门”按钮。
- [x] dashboard 目标是具备全部控制能力，具体控制项后续再细化。
- [x] 系统会有某种形式的数据库存储。

### 硬件模块

#### RC522 RFID 模块

- [x] 提供 RFID 卡读写能力。
- [x] 参与开关门流程。
- [x] 已确定用于取件认证。
- [x] 需要支持 ID 卡权限管理场景，包括临时授予 / 取消某张卡的开门权限。

#### 舵机

- [x] 通过特定角度模拟柜门开门 / 关门。
- [x] 需要响应系统控制进行开门 / 关门。
- [x] 需要响应 dashboard 的主动开门 / 关门操作。

#### 按钮

- [x] 作为物理输入设备使用。
- [x] 主要场景是外部提醒用户。
- [x] 当前业务定位偏向“配送员请求开门”按钮。

#### PIR 人体 / 运动传感器

- [x] 用于感知人靠近或经过。
- [x] 感知到人后，会激活某些系统状态。

#### 蜂鸣器 + 三极管驱动

- [x] 具备声音提示 / 提醒能力。
- [x] 蜂鸣器通过三极管驱动，而不是直接由控制引脚裸驱动。

#### 四针 RGB LED

- [x] 当前原型包含一个四针 RGB LED。
- [x] 当前接线图标注为 `Common Anode`，即共阳 RGB LED。
- [x] 提供多色灯光输出能力。

## 计划加入的能力

- [ ] 增加摄像头模块，型号暂未决定。
- [ ] 提供 dashboard，通过前端网页在局域网内访问。
- [ ] 评估是否接入 Cloudflare Tunnel，使外网也能访问 dashboard。
- [ ] 可能加入人脸检测能力。
- [ ] 人脸检测只需要“检测到人脸”，不需要做人脸识别/身份识别。
- [ ] 在检测到人脸后，尝试抓拍清晰帧。

## 待确认事项

- [ ] 快递柜业务流程细节：
  - [ ] RFID 是否也参与存件流程 / 存件绑定。
  - [ ] 开门后、关门后分别要记录哪些状态变化和日志。
- [ ] 摄像头选型：
  - [ ] 树莓派官方 Camera Module 还是 USB 摄像头。
  - [ ] 分辨率、低照度表现、是否需要自动对焦。
- [ ] 图像能力边界：
  - [ ] 人脸检测是实时预览检测，还是 PIR 触发后再检测。
  - [ ] 清晰帧抓拍的判定标准与保存策略。
  - [ ] 前端是长期展示视频流、按开关临时查看视频流，还是只查看抓拍照片。
- [ ] dashboard 范围：
  - [ ] 是否需要账号权限与访问控制。
  - [ ] “控制能力”具体包括哪些操作项（如卡权限管理、抓拍、日志查看、设备测试、远程报警等）。
- [ ] 公网访问策略：
  - [ ] 是否真的开放公网。
  - [ ] 若使用 Cloudflare Tunnel，哪些页面/接口允许暴露，哪些仅限局域网。
- [ ] 按钮与蜂鸣器的关系：
  - [ ] 按钮按下后是否触发 buzzer。
  - [ ] buzzer 的触发规则是本地提示、网页联动，还是两者都有。
- [ ] RGB LED 的灯效策略：
  - [ ] 分别用哪些颜色 / 闪烁模式表示待机、有人接近、请求开门、已开门、异常等状态。
- [ ] 数据存储方案：
  - [ ] 具体使用哪种数据库。
  - [ ] 需要保存哪些核心数据（卡权限、开门记录、抓拍记录、设备状态、告警事件等）。

## 近期拆分程序前可直接继续整理的方向

- [ ] 明确“设备侧控制”“图像处理”“Web dashboard”“数据存储/日志”“远程访问”这几部分的边界。
- [ ] 为每个硬件模块补一份引脚表和控制目标。
- [ ] 把快递柜主流程画成状态机：
  - [ ] 待机
  - [ ] 检测到人 / 接近
  - [ ] 认证
  - [ ] 开柜
  - [ ] 关柜
  - [ ] 记录日志 / 抓拍
- [ ] 明确哪些能力必须本地运行，哪些能力可以延后或放到服务端/网页端。

## 后端项目结构建议

### 建议目录

```text
iot_locker/
├─ main.py
├─ config.py
├─ drivers/
│  ├─ rc522.py
│  ├─ servo_lock.py
│  ├─ button.py
│  ├─ pir.py
│  ├─ buzzer.py
│  ├─ rgb_led.py
│  └─ camera.py
├─ services/
│  ├─ locker_service.py
│  ├─ access_service.py
│  ├─ alert_service.py
│  └─ camera_service.py
├─ web/
│  ├─ routes.py
│  └─ schemas.py
├─ storage/
│  ├─ db.py
│  └─ models.py
└─ scripts/
   └─ hardware_smoke_test.py
```

### 文件职责

- `main.py`
  - 程序入口。
  - 初始化配置、硬件驱动、service、Web 服务。
- `config.py`
  - 统一管理 GPIO 引脚、数据库路径、摄像头参数、调试开关等配置。

### drivers

- `drivers/rc522.py`
  - `RC522Reader` 类。
  - 提供读卡、取 UID、写卡等最直接能力。
- `drivers/servo_lock.py`
  - `ServoLock` 类。
  - 提供开门、关门、设定角度。
- `drivers/button.py`
  - `ButtonInput` 类。
  - 提供按钮状态读取和按下检测。
- `drivers/pir.py`
  - `PirSensor` 类。
  - 提供人体 / 运动状态读取。
- `drivers/buzzer.py`
  - `Buzzer` 类。
  - 提供开关、短鸣、指定时长鸣叫。
- `drivers/rgb_led.py`
  - `RgbLed` 类。
  - 提供设定颜色、关闭、闪烁。
- `drivers/camera.py`
  - `CameraDevice` 类。
  - 预留拍照、取帧、开关视频流能力。

### services

- `services/locker_service.py`
  - 柜门相关业务编排。
  - 协调 RFID、舵机、日志、状态切换。
- `services/access_service.py`
  - 卡权限管理与开门鉴权。
  - 支持授予 / 取消某张卡开门权限。
- `services/alert_service.py`
  - 按钮、蜂鸣器、RGB LED 的联动逻辑。
- `services/camera_service.py`
  - 摄像头抓拍与后续图像处理入口。

### web

- `web/routes.py`
  - 对前端暴露状态查询和控制接口。
- `web/schemas.py`
  - Web API 的请求 / 响应数据结构。

### storage

- `storage/db.py`
  - 数据库连接、初始化、会话管理。
- `storage/models.py`
  - 卡权限、事件日志、抓拍记录、设备状态等数据模型。

### scripts

- `scripts/hardware_smoke_test.py`
  - 单独测试每个硬件驱动是否可用。

### 当前推荐开发顺序

- [ ] 先完成 `drivers/`，每个硬件先提供最直接、最少包装的类接口。
- [ ] 写 `scripts/hardware_smoke_test.py`，逐个验证硬件是否工作。
- [ ] 再写 `services/`，把驱动拼成业务流程。
- [ ] 最后接 `web/` 和 `storage/`。

### 驱动层约束

- [ ] `drivers/` 只负责直接操作硬件，不处理业务规则。
- [ ] 每个驱动尽量封装成独立类，接口保持简单直接。
- [ ] 后续业务逻辑统一放到 `services/`，避免 GPIO 细节散落到路由或主流程里。
