# lyricmv

**一首歌加幾張圖，自動做成歌詞 MV。** 用 Whisper 把歌詞對到人聲上，每張圖緩慢推鏡（Ken Burns），
在段落開始時換圖，字幕直接燒進畫面，全部在一次 FFmpeg 編碼裡完成。macOS、Windows、Linux、Docker 都能用。

[English](README.md)

```
song.wav ────────────────────────────────────────┐
vocals.wav ──► Whisper ──► 對齊 lyrics.txt ──► 字幕（ASS＋SRT）
圖片／影片 ──────────────────────────────────────►├──► FFmpeg 一次合成 ──► song.mp4
scenes.json（哪個段落用哪張圖）────────────────────┘    推鏡・轉場・底片顆粒・字幕・淡入淡出
```

- **歌詞時間準**：Whisper 的文字只拿來當時鐘，原始歌詞逐字跟它比對。聽錯的同音字、簡繁混用、間奏幻覺出來的「作詞作曲」
  都不會出現在畫面上；Whisper 漏掉的句子會自動推算，並標出來請你確認
- **跟著段落換圖**：歌詞用 `[Verse]`、`[Chorus]`、`[Bridge]`… 標好段落，每段指定一張圖，轉場在該段第一個字唱出前 1 秒開始
- **圖片或影片片段都行**：場景也可以放 AI 影片模型生成的幾秒動態片段（例如
  [WanGP](https://github.com/deepbeepmeep/Wan2GP) 的圖生影片），片段比段落短會自動循環；歌詞時間、轉場、顆粒、字幕照樣由 lyricmv 處理
- **推鏡不抖**：用 `perspective` 做次像素取樣；常見的 `zoompan` 會取整數像素，慢速推鏡時畫面會抖
- **快**：每張圖只解碼一次；能用硬體 H.264（VideoToolbox、NVENC、Quick Sync、AMF）就用，不行就用 libx264。
  3 分半、7 個場景的歌，在 M2 Max 上約 75 秒做完
- **直接上 YouTube**：1080p30、BT.709 色彩標記，另外產生 SRT 可以上傳成 CC 字幕
- 內附可商用的開源中文字型（霞鶩文楷 TC、思源黑體 TC）

針對中文歌詞設計（逐字比對）。其他語言可以用 `--language` 指定，但測試得比較少。

## 安裝

需要 **Python 3.10 以上**，以及**有 libass 的 FFmpeg**（燒字幕用）。

| 系統 | FFmpeg |
|---|---|
| macOS | `brew install ffmpeg-full`（Homebrew 一般的 `ffmpeg` 沒有 libass；lyricmv 會自動找到 `ffmpeg-full`） |
| Windows | `winget install Gyan.FFmpeg` 或 `choco install ffmpeg-full` |
| Ubuntu / Debian | `sudo apt install ffmpeg` |

接著安裝 lyricmv（用 [pipx](https://pipx.pypa.io/) 會自動建立獨立環境）：

```bash
pipx install git+https://github.com/softwarejob/lyricmv
# Apple Silicon：加裝快很多的 MLX 版 Whisper
pipx install "lyricmv[mlx] @ git+https://github.com/softwarejob/lyricmv"
```

檢查環境：

```bash
lyricmv doctor
lyricmv demo        # 產生 12 秒的範例影片 lyricmv-demo.mp4（不需要 Whisper）
```

要指定某個 FFmpeg：設環境變數 `LYRICMV_FFMPEG=/path/to/ffmpeg`。

## 做一支 MV

需要準備：

1. **整首歌**（`song.wav`、mp3、flac…）
2. **人聲分軌**（`vocals.wav`），強烈建議。Suno 可以匯出分軌；其他歌可以用 [Demucs](https://github.com/facebookresearch/demucs)
   或 UVR 分離。沒有分軌時會直接對整首歌，準確度比較差
3. **lyrics.txt**，用段落標籤分段（格式見下方）
4. **一張圖**（或一段影片），或是多張圖加一個 **scenes.json**

```bash
# 整首歌一張圖
lyricmv make --audio song.wav --vocals vocals.wav --lyrics lyrics.txt --image cover.png

# 每個段落換不同的圖
lyricmv make --audio song.wav --vocals vocals.wav --lyrics lyrics.txt --scenes scenes.json
```

影片輸出到 `song.mp4`；Whisper 結果、對齊後的歌詞和字幕放在 `lyricmv-work/song/`。
第一次執行會下載 Whisper 模型（約 1.6 GB）。3 分半的歌，Apple Silicon 用 MLX 轉錄約 15 秒，用 CPU 約 3 分鐘。

執行時會列出每一句的時間和比對率。標 `<- check` 的句子大多是推算的，看片時注意這幾段。
時間不對的話，直接改 `lines.json`，再重跑下面的 `subs` 和 `render` 兩步；Whisper 結果有快取，不會重新轉錄。

### lyrics.txt

```
[Verse 1: soft piano only]
窗外的雨 下了一整夜
桌上的燈 還亮著

[Chorus: drums enter]
慢慢來 沒關係
天總會亮的

[Verse 2]
...

[Chorus]
慢慢來 沒關係
```

- 每一句歌詞屬於它上面最近的 `[段落]`；標籤裡 `:` 後面的文字會被忽略，所以可以直接用貼給 Suno 的那份歌詞（含演唱指示）
- 只出現一次的段落用原名（`Verse 2`）；重複的段落會編號：`Chorus#1`、`Chorus#2`
- 中文句子裡的半形空白代表斷句，字幕上會顯示成全形空白

### scenes.json

```json
{
  "scenes": [
    {"from": "start",    "image": "verse.png"},
    {"from": "Chorus#1", "image": "chorus.png"},
    {"from": "Verse 2",  "image": "verse.png"},
    {"from": "Chorus#2", "image": "chorus.png"}
  ]
}
```

第一個場景一定要是 `"start"`。圖片路徑以 JSON 檔所在的資料夾為準（或用 `--images-dir` 指定）；沒寫副檔名時會自動找
`名稱.png`、`名稱.jpg`…。任何比例的圖都可以，會先填滿 16:9 再從中間裁切。要畫面銳利，圖至少 2208×1242
（1920×1080 再加上推鏡的空間）。[`examples/song`](examples/song) 有範例 lyrics.txt 和 scenes.json（歌和圖請自備）。

#### 影片片段

場景也可以用影片檔（`.mp4`、`.mov`、`.webm`、`.mkv`），例如用 AI 影片模型把某張圖做成 5–10 秒的動態片段
（像是 [WanGP](https://github.com/deepbeepmeep/Wan2GP) 的 Wan 2.2 圖生影片）。寫法跟圖片一樣：

```json
{"from": "Chorus#1", "image": "chorus.mp4"}
```

- 片段在該段落開始時出現，轉場和圖片一樣，上面一樣加顆粒、燒字幕
- 片段比場景短就循環播放，比場景長就截掉；最後一格和第一格越接近，循環越看不出接縫
- 片段不推鏡（本身就在動），片段自己的聲音一律忽略
- 任何尺寸、比例、幀率都可以：會填滿 1920×1080 再裁切，並轉成 30 fps。16 fps 的片段得重複畫格，看起來會有點頓，
  工具能補幀的話先補到 30 fps
- `--image clip.mp4` 就是整首歌只用一段片段
- 同一個資料夾裡同時有 `chorus.png` 和 `chorus.mp4` 時要寫副檔名，只寫 `chorus` 會分不出是哪一個

### 分步執行

`make` 其實是依序跑下面三個指令，也可以分開跑：

```bash
lyricmv align  --vocals vocals.wav --lyrics lyrics.txt --out work/      # → whisper.json、lines.json
lyricmv subs   --lines work/lines.json                                  # → lyrics.ass、lyrics.srt
lyricmv render --audio song.wav --scenes scenes.json --lines work/lines.json --subs work/lyrics.ass
```

### 常用選項

| 選項 | 預設 | 說明 |
|---|---|---|
| `--zoom` | 1.15 | 圖片場景的推鏡倍率，1.0 = 不動；單數場景推近、雙數拉遠；影片片段不推鏡 |
| `--transition` | fade | 任何 [xfade](https://ffmpeg.org/ffmpeg-filters.html#xfade) 轉場：`dissolve`、`smoothleft`、`circleopen`… |
| `--transition-duration` | 1 | 轉場秒數 |
| `--grain` | 6 | 底片顆粒 0–30，0 = 關閉 |
| `--fade-in` / `--fade-out` | 1.5 / 2 | 片頭淡入、片尾淡出秒數（畫面和聲音） |
| `--font`、`--size`、`--margin` | LXGW WenKai TC Medium、72、80 | 字幕字型、字級、離底部距離；也內附 `"Noto Sans TC Medium"` |
| `--encoder` | auto | `libx264`、`h264_videotoolbox`、`h264_nvenc`、`h264_qsv`、`h264_amf` |
| `--bitrate` / `--crf` | 12M / 18 | 硬體編碼的位元率（也是 libx264 的上限）；libx264 的畫質 |
| `--language` | zh | Whisper 的語言，或 `auto` |
| `--backend` / `--model` | auto | `mlx`（Apple Silicon）或 `faster`（faster-whisper，所有平台） |
| `--force` | | 覆寫已存在的影片（不加的話會拒絕覆寫） |

完整選項：`lyricmv <指令> --help`。

## Docker

```bash
docker build -t lyricmv https://github.com/softwarejob/lyricmv.git
docker run --rm -v "$PWD:/work" -v lyricmv-models:/models lyricmv \
  make --audio song.wav --vocals vocals.wav --lyrics lyrics.txt --image cover.png
```

Docker 版用 CPU 編碼（libx264）和 CPU 跑 Whisper。`lyricmv-models` volume 會保留下載過的 Whisper 模型。
Linux 上加 `--user "$(id -u):$(id -g)"`，輸出的影片才不會變成 root 的檔案。

## 運作原理

- **對齊**：兩邊文字都轉成簡體、只留字母數字，用 `difflib` 逐字比對。對上的字用 Whisper 的時間；同一句裡字數相同的錯字
  視為同音誤聽，也借用時間；句首句尾對不到的字每字推 0.35 秒；整句對不到的，在前後句之間依字數分配。
  第一句以人聲分軌實際出聲的時間為錨點。Whisper 關掉 `condition_on_previous_text`，避免重複的副歌讓它卡在迴圈
- **字幕**：比開口早 0.25 秒出現、唱完多停 0.5 秒、淡入淡出 0.3 秒；和下一句間隔小於 0.6 秒就直接接上，避免閃爍
- **畫面**：每張圖只縮放一次到留有推鏡空間的工作尺寸（1.15 倍時 2208×1242），循環後用 `perspective`
  （cubic、逐格計算）推鏡，縮到 1920×1080，再用 `xfade` 接起來。顆粒加在最後的 1080p 像素上（不會跟著推鏡變大、
  轉場時不會兩層疊加），只加亮度。最後才燒字幕和淡入淡出。影片片段用 `-stream_loop -1` 讀進來，轉成固定 30 fps、
  裁成場景的格數、填滿 1920×1080，再跟圖片一樣用 `xfade` 接起來
- **色彩**：RGB 轉 YUV 用 BT.709，並在每一格標上 BT.709，上傳 YouTube 後顏色不會跑掉。影片片段依它自己的色彩標記轉成
  BT.709（沒有標記的當成 BT.601，和 FFmpeg 的預設一樣）

## 開發

```bash
git clone https://github.com/softwarejob/lyricmv && cd lyricmv
python -m venv .venv && . .venv/bin/activate     # Windows：.venv\Scripts\activate
pip install -e ".[test]"
pytest
```

## 授權

lyricmv 採 MIT 授權。內附字型採 SIL Open Font License 1.1
（[霞鶩文楷 TC](https://github.com/lxgw/LxgwWenkaiTC)、[思源黑體 TC](https://github.com/notofonts/noto-cjk)），
授權文件在 `src/lyricmv/fonts/licenses/`。lyricmv 會呼叫 FFmpeg，但不包含 FFmpeg；Docker 映像檔裡的是 Debian 的
FFmpeg 套件。Whisper 模型從 Hugging Face 下載，依各自的授權（MIT）。

發布前請確認你擁有音樂、圖片和影片片段的使用權。
