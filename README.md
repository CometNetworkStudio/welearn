# OmniTask Script · WeLearn（welearn）

WeLearn（welearn.sflep.com）自动挂时长 / 提交进度脚本，适配 [OmniTask](https://github.com/CometNetworkStudio/OmniTask) 平台，也可独立运行。

## 简介

- 登录后自动完成课程 SCO 的「挂时长」或「提交进度」。
- 支持按课程 / 单元 / 数量限制选择，跳过已完成与不可见 SCO。
- 既可被 OmniTask 以子进程（stdio JSON）调用，也可本地 CLI 单跑。

## 免责声明

本项目**仅供个人学习与技术研究使用**。请遵守 WeLearn 平台服务条款与所在学校规定，因使用本项目产生的一切后果由使用者自行承担。请勿用于商业牟利或倒卖。

## 净室重写声明

本脚本为**独立实现**，仅依据平台公开网络接口行为编写，**未复制任何第三方项目源码**。参考项目 `jhl337/Auto_WeLearn`（无开源协议，默认保留所有权利）仅用于理解协议；本项目代码为其净室重写版本，采用 MIT 协议开源。

## 用法

### 方式一：独立 CLI

```bash
pip install -r requirements.txt   # 从主仓库子目录安装 OmniTask SDK
python main.py --cli \
  --action progress \
  --credential username=<账号> --credential password=<密码> \
  --param cid=2416 --param limit=1
```

- `--action`：`time`（挂时长）/ `progress`（提交进度）。
- `--param k=v` / `--credential k=v`：可重复，见 `script.json`。

### 方式二：OmniTask 平台调用

OmniTask 的 Go Host 以子进程启动 `main.py`，经 stdin 下发 `execute`，stdout 输出事件。协议见：
<https://github.com/CometNetworkStudio/OmniTask/blob/main/docs/script-protocol.md>

## 参数（`params`）

| key | 默认 | 说明 |
|---|---|---|
| `cid` | 空(第一门课) | 课程 id |
| `unit_idx` | 空(全部) | 单元数字下标（0 起） |
| `duration` | 60 | 挂时长秒数（`action=time`） |
| `accuracy` | 100 | 提交进度正确率（`action=progress`） |
| `include_completed` | false | 是否也处理已完成 SCO |
| `limit` | 0 | 最多 SCO 数，0=不限 |

## 凭据

| key | 说明 |
|---|---|
| `username` | WeLearn 账号 |
| `password` | WeLearn 密码 |

## 目录

```
.
├── welearn/        # 协议实现（crypto/client/runner）
├── main.py         # 入口（Host 模式 / CLI）
├── cli.py          # 本地命令行
├── requirements.txt# 依赖（安装 omnitask-sdk）
└── script.json     # manifest
```

## License

MIT © CometNetworkStudio
