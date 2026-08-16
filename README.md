# PPT 转视频 AI 工具

将 PDF 课件一键转换为**带旁白音频**与 **MP4 视频**的 AI 工具。

> **注意**：受字体渲染限制，当前版本仅支持 **PDF → 视频**。PDF 为固定排版，可直接转为图片进行视频合成；PPTX 渲染依赖系统字体，中文字体缺失时排版错乱，故暂不支持，规划后续集成 LibreOffice 渲染解决。

核心流水线：

```
上传课件 (PDF)
      │
      ▼
AI 生成讲稿 (DeepSeek)
      │
      ▼
语音合成 (vLLM-Omni + Qwen3-TTS)
      │
      ▼
ffmpeg 合成视频 (1920×1080 MP4)
```

- **后端**：FastAPI + aiosqlite（SQLite）
- **前端**：Jinja2 + Alpine.js + Tailwind CSS + Axios
- **讲稿生成**：DeepSeek（OpenAI 兼容接口）
- **语音合成**：vLLM-Omni 多阶段推理引擎 + Qwen3-TTS 模型（本地 GPU 推理，无需远程 API）
- **音视频处理**：ffmpeg / pydub / soundfile / sox

---

## 目录

- [功能特性](#功能特性)
- [目录结构](#目录结构)
- [安装与部署](#安装与部署)
- [端口说明](#端口说明)
- [使用流程](#使用流程)
- [配置说明](#配置说明)
- [API 接口一览](#api-接口一览)
- [架构与模块设计](#架构与模块设计)
- [数据模型](#数据模型)
- [常见问题 FAQ](#常见问题-faq)

---

## 功能特性

| 功能 | 说明 |
| --- | --- |
| 课件解析 | 支持 PDF 上传，自动提取标题、正文，渲染每页图片；文本过少时自动 OCR 兜底（tesseract / easyocr） |
| AI 讲稿生成 | 基于 DeepSeek 为每页生成自然教学口吻的旁白，支持批量与单页生成、字数控制（100–500）、参考文件增强、课程主题自动生成 |
| 语音合成 | 使用 vLLM-Omni 部署 Qwen3-TTS 模型：**CustomVoice** 提供 9 种预设音色；**Base** 支持上传参考音频进行声音复刻 |
| 参数调节 | 支持语速、种子（Seed）、**温度（Temperature）** 调节 |
| 音频合成 | 将各页音频按顺序拼接（间隔 300ms 静音），导出整段音频 |
| 视频合成 | 每页图片循环铺满对应音频时长，缩放/填充至 1920×1080，拼接为 MP4 |
| 并发安全 | `asyncio.Lock` 串行化 GPU 推理，批量生成与单页生成自动排队，避免显存溢出 |
| 项目隔离 | 项目以 **UUID** 作为对外标识，不可枚举访问他人项目 |
| 声音管理 | 独立的声线管理页，注册/删除自定义克隆声音 |
| Web 工作台 | 项目列表 + 单项目工作台，全流程可视化操作，后台任务进度轮询 |

### 预设音色（CustomVoice 模型）

| 音色 | 描述 | 母语 |
| --- | --- | --- |
| Vivian | 明亮略带锋芒的年轻女声 | 中文 |
| Serena | 温暖柔和的年轻女声 | 中文 |
| Uncle_Fu | 低沉醇厚的成熟男声 | 中文 |
| Dylan | 清亮自然的北京男声 | 中文（北京话） |
| Eric | 活泼略带沙哑的成都男声 | 中文（四川话） |
| Ryan | 节奏感强的动感男声 | 英语 |
| Aiden | 阳光清亮的美式男声 | 英语 |
| Ono_Anna | 轻快灵动的日本女声 | 日语 |
| Sohee | 温暖富有情感的韩国女声 | 韩语 |

---

## 目录结构

```
ppt_to_audio/
├── run.py                  # 应用入口（uvicorn）
├── run.sh                  # 简单启动脚本（conda 环境 ppt2video）
├── deploy.sh               # 部署脚本
├── requirements.txt        # Python 依赖
├── data.db                 # SQLite 数据库（运行后自动创建）
├── app/
│   ├── main.py             # FastAPI 应用、路由注册、页面渲染、GPU 清理
│   ├── config.py           # 全局配置（路径、模型、环境变量）
│   ├── models/
│   │   ├── database.py     # SQLite 连接与建表 SCHEMA（含 uuid 迁移）
│   │   └── schemas.py      # Pydantic 请求/响应模型
│   ├── routers/            # API 路由层
│   │   ├── project.py      # 项目与幻灯片管理、课件上传（UUID 路由）
│   │   ├── script.py       # AI 讲稿生成
│   │   ├── audio.py        # 语音合成（批量/单页，后台任务）
│   │   ├── voice.py        # 声音克隆管理
│   │   ├── video.py        # 视频合成与下载
│   │   ├── model.py        # TTS 模型切换（Base / CustomVoice）
│   │   └── digital_human.py# 数字人（占位，未实现）
│   └── services/           # 业务服务层
│       ├── vllm_process.py # vLLM-Omni 子进程管理（启动/停止/健康检查/模型切换）
│       ├── vllm_omni_tts.py# vLLM-Omni 语音合成（分句、声音克隆、推理锁）
│       ├── local_tts.py    # 本地 Qwen3-TTS 合成（旧后端，兼容保留）
│       ├── api_tts.py      # 远程 API 合成（兼容保留）
│       ├── tts_backend.py  # TTS 后端分发器
│       ├── ppt_parser.py   # PPTX 解析、参考文件文本提取
│       ├── pdf_parser.py   # PDF 解析 + OCR 兜底
│       ├── script_generator.py  # DeepSeek 讲稿生成
│       ├── voice_clone_service.py  # 克隆声音存储
│       ├── tts_engine.py   # 文本分句
│       ├── thumbnails.py   # 幻灯片缩略图生成
│       ├── audio_composer.py    # 音频拼接
│       └── video_composer.py    # ffmpeg 视频合成
├── scripts/
│   ├── setup_conda.sh      # 一键环境安装（含 CUDA Toolkit + vLLM-Omni）
│   ├── start_all.sh        # 一键启动（vLLM-Omni 自启动 + 应用，app=8003 / vllm=8000）
│   ├── download_models.py  # 下载 Qwen3-TTS 模型
│   └── patch_vllm_temperature.py  # vLLM 温度参数修补脚本
├── models/                 # 本地模型权重（不入库）
│   ├── Qwen3-TTS-12Hz-0.6B-Base/         # 声音复刻模型
│   ├── Qwen3-TTS-12Hz-1.7B-Base/         # 通用 base 模型
│   └── Qwen3-TTS-12Hz-1.7B-CustomVoice/  # 预设音色模型
├── templates/              # Jinja2 页面
│   ├── index.html          # 项目列表
│   ├── workspace.html      # 项目工作台
│   └── voice_manager.html  # 声音管理
├── voices/                 # 克隆声音（不入库）
├── uploads/                # 上传的课件与参考文件（不入库）
└── outputs/                # 生成的音频 / 视频（不入库）
```

---

## 安装与部署

### 1. 系统依赖

需要预先安装以下系统工具：

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg sox poppler-utils tesseract-ocr tesseract-ocr-chi-sim
```

- `ffmpeg`：视频合成
- `sox`：音频处理
- `poppler-utils`：PDF 文本与图片提取（`pdftotext` / `pdftoppm`）
- `tesseract-ocr` + 中文包：PDF OCR 兜底（可选，缺失时回退 easyocr）

### 2. 一键安装环境

```bash
bash scripts/setup_conda.sh
```

该脚本会自动完成：安装 Miniconda → 创建 conda 环境 `ppt2video`（Python 3.12）→ 安装 `requirements.txt` → 安装 PyTorch（CUDA）与 `qwen-tts` → 安装 sox → **安装 CUDA Toolkit（nvcc，flashinfer JIT 编译必需）→ 安装 vLLM-Omni（含依赖）** → 下载 Qwen3-TTS CustomVoice 模型。

> 脚本会执行 `conda install -c nvidia cuda-toolkit=13.2.2`，并用 pip 安装 vLLM 全家桶。若环境被重建导致 vLLM 丢失，重跑一次本脚本即可全部恢复。

### 3. 安装 vLLM-Omni（语音合成引擎）

> 已包含在 `setup_conda.sh` 中，可跳过本节；如需手动安装，务必使用**已验证的版本组合**（见下）：

```bash
conda activate ppt2video
conda install -c nvidia cuda-toolkit=13.2.2 -y
pip install vllm==0.26.0 vllm-omni==0.26.0 flashinfer-python==0.6.14 -i https://pypi.tuna.tsinghua.edu.cn/simple --default-timeout=1000
pip install -U quack-kernels nvidia-cutlass-dsl -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**版本兼容性（重要，不可随意更换）**：

| 组件 | 版本 | 原因 |
| --- | --- | --- |
| `vllm` | `0.26.0` | `0.25.x` 移除了 `OmniRequest.num_in_flight_tokens`，推理必崩；`0.24.x` 缺少 `vllm.entrypoints.scale_out`，vllm-omni 无法导入 |
| `vllm-omni` | `0.26.0` | 与 vllm 0.26 配套（版本对齐校验） |
| `flashinfer-python` | `0.6.14` | vllm 0.26 的固定依赖 |
| `quack-kernels` | `>=0.6.4` | `0.5.0` 与 cutlass 4.6 不兼容，报 `cutlass.cute.core` 无 `ThrMma` |
| `cuda-toolkit` | `13.2.2` | 提供 `nvcc`；缺失时报 `Could not find nvcc`，flashinfer 无法 JIT 编译采样 kernel |

> 需 NVIDIA GPU 与 CUDA 环境。vLLM-Omni 用于部署 Qwen3-TTS 多阶段推理服务。

### 4. 下载模型

`Base` 模型需手动放置到 `models/Qwen3-TTS-12Hz-0.6B-Base`；`CustomVoice` 模型可由脚本下载：

```bash
python scripts/download_models.py
```

### 5. 启动服务

一键启动（推荐，含 vLLM-Omni 引擎自启动 + base 模型加载）：

```bash
bash scripts/start_all.sh
```

或分别启动：

```bash
# 终端 1：启动 vLLM-Omni TTS 引擎
conda activate ppt2video && vllm serve models/Qwen3-TTS-12Hz-0.6B-Base --omni --port 8000 --host 0.0.0.0

# 终端 2：启动应用
conda activate ppt2video && python run.py
```

访问 <http://localhost:8003>（应用端口，见下节说明）。

> ⚠️ **不要用 `run.sh` / `run.py` 替代 `start_all.sh`**：`run.sh` 仅启用本地 TTS 后端（不启动 vLLM），`run.py` 固定 8003 端口且需先手动启动 vLLM。日常使用请始终执行 `bash scripts/start_all.sh`。

---

## 端口说明

| 端口 | 用途 |
| --- | --- |
| `8000` | vLLM-Omni API Server（TTS 推理服务） |
| `8001 / 8002` | vLLM 多阶段引擎内部 NCCL 通信端口（自动占用） |
| `8003` | Web 应用（FastAPI） |

> **为什么应用不用 8000–8002？** vLLM-Omni 的多阶段引擎（StageEngineCoreProc）会按顺序尝试 8000 → 8001 → 8002 作为 NCCL 通信端口，API Server 固定占用 8000。若应用占用其中任一端口，vLLM 将无法绑定，base 模型无法自启动。因此应用固定使用 `8003`，且应用进程不得与 vLLM 同端口。
>
> 早期版本 `run.py` 曾硬编码 `8000`（与 vLLM 冲突），现已改为 `8003`。

---

## 使用流程

1. **创建项目**：首页填写项目名称（可选课程主题）。
2. **上传课件**：进入工作台，上传 PDF，系统自动解析为分页并渲染预览图。
3. **（可选）上传参考文件**：支持 `.txt/.md/.pdf/.docx`，用于增强讲稿内容。
4. **生成讲稿**：选择字数与 LLM 模型，点击「一键生成讲稿」或单页生成，可手动编辑。
5. **设置声音**：选择预设音色，或选择已注册的克隆声音；调节语速、温度、种子。
6. **生成音频**：点击「生成全部音频」或单页生成，完成后可在线预览。
7. **生成视频**：所有页面音频就绪后，点击「生成视频」，完成后下载 MP4。

声音克隆：进入「声音管理」页（`/voices`），上传 3–10 秒参考音频并填写对应文本即可注册。

---

## 配置说明

配置集中在 `app/config.py`，多数可通过环境变量覆盖。

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `TTS_BACKEND` | `local` | 语音后端：`vllm_omni`（推荐）/ `local` |
| `VLLM_OMNI_BASE_URL` | `http://localhost:8000` | vLLM-Omni 服务地址 |
| `VLLM_PORT` | `8000` | vLLM-Omni 服务端口 |
| `VLLM_OMNI_MODEL` | `base` | TTS 模型：`base`（声音克隆）/ `customvoice`（预设音色） |
| `VLLM_OMNI_GPU_COOLDOWN` | `0` | 分段推理间的 GPU 冷却等待（秒），默认不等待 |
| `DEEPSEEK_API_KEY` | 见下方说明 | DeepSeek API 密钥（**通过环境变量注入**） |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | DeepSeek 接口地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | 讲稿生成所用模型 |
| `TTS_DEVICE` | `cuda` | 本地 TTS 推理设备（旧后端） |

> **DeepSeek 密钥**：`app/config.py` 中 `DEEPSEEK_API_KEY` 仅作本地占位默认值（`my_api_key`）。部署到生产/公开环境前，务必通过环境变量注入你自己的真实密钥：
> ```bash
> export DEEPSEEK_API_KEY=你的真实密钥
> ```

固定路径配置（相对项目根目录）：

| 配置 | 值 | 说明 |
| --- | --- | --- |
| `VLLM_BASE_MODEL_PATH` | `models/Qwen3-TTS-12Hz-0.6B-Base` | 声音复刻模型路径 |
| `VLLM_CUSTOMVOICE_MODEL_PATH` | `models/Qwen3-TTS-12Hz-1.7B-CustomVoice` | 预设音色模型路径 |
| `MAX_UPLOAD_SIZE_MB` | `100` | 课件上传大小上限 |
| `SUPPORTED_REFERENCE_FORMATS` | `.txt/.md/.pdf/.docx` | 参考文件支持格式 |

---

## API 接口一览

> 所有 `/api/projects/*` 路由均使用 **UUID** 标识项目（如 `/api/projects/5e6b680732f046eba12d22f3bf100212`），不可枚举。

### 项目与幻灯片 `/api/projects`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/` | 创建项目（自动生成 UUID） |
| GET | `/` | 项目列表 |
| GET | `/{project_uuid}` | 项目详情 |
| PUT | `/{project_uuid}` | 更新名称/主题 |
| DELETE | `/{project_uuid}` | 删除项目 |
| POST | `/{project_uuid}/upload-pptx` | 上传并解析 PPTX |
| POST | `/{project_uuid}/upload-pdf` | 上传并解析 PDF |
| GET | `/{project_uuid}/pdf-file` | 获取已上传 PDF |
| POST | `/{project_uuid}/reparse` | 重新解析课件 |
| GET | `/{project_uuid}/slides` | 幻灯片列表 |
| GET | `/{project_uuid}/resume` | 重置项目状态 |
| POST | `/{project_uuid}/reference-files` | 上传参考文件 |
| GET | `/{project_uuid}/reference-files` | 参考文件列表 |
| DELETE | `/{project_uuid}/reference-files/{file_id}` | 删除参考文件 |
| GET | `/{project_uuid}/slide-image/{slide_number}` | 获取幻灯片图片 |

### 讲稿 `/api/scripts`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/generate` | 批量生成讲稿（后台任务） |
| GET | `/generate/task/{task_id}` | 查询任务进度 |
| POST | `/slides/{slide_id}/generate` | 单页生成讲稿 |
| PUT | `/slides/{slide_id}` | 编辑旁白 |
| POST | `/{project_uuid}/auto-topic` | 自动生成课程主题 |

### 音频 `/api/audio`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/generate` | 生成音频（整项目或单页，后台任务） |
| POST | `/regenerate/{slide_id}` | 重新生成单页音频 |
| GET | `/task/{task_id}` | 查询任务进度 |
| GET | `/slide/{slide_id}` | 获取单页音频路径 |

### 声音 `/api/voices`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 声音列表 |
| POST | `/` | 注册克隆声音 |
| DELETE | `/{name}` | 删除声音 |
| GET | `/audio/{name}` | 获取参考音频 |

### 模型 `/api/model`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/status` | 当前模型与切换状态 |
| POST | `/switch` | 切换 Base / CustomVoice 模型 |

### 视频 `/api/video`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/generate` | 生成视频（后台任务） |
| GET | `/task/{task_id}` | 查询任务进度 |
| GET | `/download/{project_uuid}` | 下载视频 |

### 数字人 `/api/digital-human`（占位，未实现）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/status` | 返回 `available: false`（规划使用 MuseTalk） |
| POST | `/generate` | 返回 `not_implemented` |

### 页面路由

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 项目列表页 |
| GET | `/workspace/{project_uuid}` | 项目工作台 |
| GET | `/voices` | 声音管理页 |

---

## 架构与模块设计

采用经典的三层结构：

- **路由层（`app/routers`）**：处理 HTTP 请求与参数校验，调用服务层。长时间任务（讲稿/音频/视频生成）通过 FastAPI `BackgroundTasks` 异步执行，并以内存字典 `_task_status` 记录进度，前端轮询 `/task/{task_id}` 获取状态。
- **服务层（`app/services`）**：封装核心业务，包括课件解析、DeepSeek 讲稿生成、vLLM-Omni 语音合成、音视频合成等。
- **数据层（`app/models`）**：`database.py` 维护单一 SQLite 连接并自动建表（含 uuid 迁移）；`schemas.py` 定义 Pydantic 模型。

### vLLM-Omni 多阶段 TTS

语音合成由独立的 vLLM-Omni 子进程提供（`vllm_process.py` 负责生命周期管理）。应用启动时（`lifespan`）若 `TTS_BACKEND=vllm_omni`，会自动拉起 `vllm serve --omni` 并加载 **base 模型**（`VLLM_OMNI_MODEL=base`），就绪后应用才完成启动：

```
vllm serve models/Qwen3-TTS-12Hz-0.6B-Base --omni --port 8000
        │
        ├── Stage-0  StageEngineCoreProc  文本 → 语音 token（AR 解码 + CUDA Graph）
        └── Stage-1  StageEngineCoreProc  token → 波形（code2wav，CUDA Graph 加速）
```

- 两阶段引擎各自加载模型并捕获 CUDA Graph，实测峰值显存约 **12GB**（含 KV cache），建议 ≥ 16GB 显存。
- 首次启动会进行 flashinfer / inductor 内核编译，CPU 内存短暂飙升属正常现象，编译完成后回落。
- 长文本经 `_segment_text` 分句，逐段调用 `/v1/audio/speech`，段间以 `VLLM_OMNI_GPU_COOLDOWN`（默认 0s）冷却，最后以 300ms 静音拼接。

### 并发控制：GPU 推理锁

`vllm_omni_tts.py` 定义模块级 `asyncio.Lock`：

```python
_inference_lock = asyncio.Lock()

async with _inference_lock:
    # 上传声音克隆、逐段推理、GPU 冷却
```

所有 TTS 推理（批量生成、单页生成、声音克隆）共享同一把锁，**同一时刻仅一个请求占用 GPU**。当"一键生成"正在推理某页时，新的单页生成请求会在锁上挂起等待，形成天然排队，避免并发推理导致显存溢出。

### 项目隔离（UUID）

`projects` 表在整数主键 `id` 之外新增 `uuid` 列：

- `id`（整数）→ 内部使用：外键关联、请求体 `project_id`、文件目录
- `uuid`（字符串）→ 对外暴露：`/workspace/{uuid}`、`/api/projects/{uuid}/*`

外部无法通过枚举数字 ID 访问他人项目。

---

## 数据模型

SQLite 共四张表（见 `app/models/database.py`）：

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `projects` | id, uuid, name, topic, ppt_filename, status, composed_audio, video_path | 项目，状态：draft / parsed / scripted / completed |
| `slides` | id, project_id, slide_number, title, content, notes, narration, narration_audio, status | 幻灯片及讲稿、音频 |
| `voices` | id, name, description, ref_audio_path, prompt_text | 克隆声音元数据 |
| `reference_files` | id, project_id, filename, file_path, content | 参考文件及提取文本 |

`slides` 与 `reference_files` 外键关联 `projects`，级联删除。

---

## 常见问题 FAQ

**Q：需要多大的显存？**
A：vLLM-Omni 多阶段引擎实测峰值约 12GB（0.6B Base 模型 + CUDA Graph + KV cache），建议 ≥ 16GB 显存。若使用旧版本地 TTS 后端（1.7B 模型），建议 ≥ 8GB。

**Q：为什么只支持 PDF 转视频？**
A：PPTX 渲染成图片依赖系统中文字体，字体缺失时排版错乱；PDF 为固定排版可稳定转图。规划通过 LibreOffice 无头渲染解决 PPTX 支持。

**Q：启动时提示端口被占用？**
A：`8000` 为 vLLM-Omni 服务，`8001/8002` 为其内部 NCCL 通信端口，应用固定使用 `8003`。请勿将应用配到 8000–8002 区间（`run.py` 已改为 8003）。启动前可清理残留：`pkill -9 -f StageEngineCoreProc && pkill -9 -f "vllm serve" && pkill -9 -f uvicorn`。

**Q：应用能起来，但 vLLM base 模型没自启动 / 启动失败？**
A：按以下顺序排查：
1. 是否用 `bash scripts/start_all.sh` 启动？（`run.sh` 不启用 vLLM 后端）
2. 日志 `logs/app.log` 是否报 `FileNotFoundError: .../bin/vllm`？→ vLLM 未安装，重跑 `bash scripts/setup_conda.sh`。
3. 日志 `logs/vllm_omni.log` 是否报 `Could not find nvcc`？→ 缺 CUDA Toolkit，`conda install -n ppt2video -c nvidia cuda-toolkit=13.2.2 -y`。
4. 日志是否报 `cutlass.cute.core has no attribute 'ThrMma'`？→ quack 版本过旧，`pip install -U quack-kernels nvidia-cutlass-dsl`。
5. 日志是否报 `OmniRequest has no attribute 'num_in_flight_tokens'`？→ vllm 版本不匹配，必须用 `vllm==0.26.0`（见安装章节版本表）。

**Q：vLLM 启动时 CPU 内存占用极高 / 模型迟迟不进显存？**
A：首次启动 flashinfer 与 inductor 会 JIT 编译 CUDA kernel，CPU 内存短暂暴涨（数 GB）属正常，编译完成后回落并加载显存。若长时间卡住且报 `Could not find nvcc`，按上一条安装 CUDA Toolkit。

**Q：显存占用到 12G 后立刻被释放、服务启动失败？**
A：通常是旧进程未清理干净导致端口冲突或显存残留。先执行：`pkill -9 -f StageEngineCoreProc && pkill -9 -f "vllm serve" && pkill -9 -f uvicorn`，再重新启动。

**Q：conda 环境被重建后 vLLM 消失了？**
A：`ppt2video` 环境一旦被 `conda create` 重建，vllm / vllm-omni / nvcc 都会丢失（不在 `requirements.txt` 中）。重跑 `bash scripts/setup_conda.sh` 会一并装回（含 CUDA Toolkit 与 vLLM-Omni）。注意不要自行 `conda create -n ppt2video` 重建环境。

**Q：模型下载很慢或失败？**
A：脚本默认从 ModelScope 下载。可手动执行 `python scripts/download_models.py`，或使用 Hugging Face 下载后放入对应目录。

**Q：PDF 解析出的文字很少或为空？**
A：扫描件或图片型 PDF 需要 OCR。安装 `tesseract-ocr tesseract-ocr-chi-sim` 后会自动启用 OCR 兜底；未安装时回退到 easyocr（首次运行会下载模型）。

**Q：如何更换 DeepSeek 密钥？**
A：通过环境变量注入：`export DEEPSEEK_API_KEY=你的密钥`。

**Q：克隆声音效果不佳？**
A：参考音频建议 3–10 秒、清晰无背景噪声，并准确填写音频对应的文本（`prompt_text`），以提升复刻质量。

**Q：数字人功能为何不可用？**
A：`/api/digital-human` 目前为占位实现，规划集成 MuseTalk 进行口型同步，尚未落地。

---

## 许可证

本项目使用 [Apache License 2.0](LICENSE)，遵循所依赖 Qwen3-TTS / Qwen 系列模型的开源许可要求。
