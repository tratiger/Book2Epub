# Book2Epub

Windowsネイティブ環境で動作する、技術書向けEPUB変換パイプラインです。スキャン・歪み補正済みのページ画像から、セマンティック構造とレイアウト意図を保持した標準準拠のリフロー型 **EPUB 3.3** を生成します。

---

## 主な特徴

* **真のリフロー型 EPUB 3.3**: 単なるスキャン画像埋め込みや固定レイアウト（Fixed-Layout）ではなく、一般的な電子書籍リーダーで最適に読めるリフロー型XHTML 5 + MathMLを出力。
* **高精度なドキュメントAI**: MinerU 3.4.5（ローカルGPU実行）の `middle.json` を唯一の入力情報源（Source of Truth）として採用。
* **二層アーキテクチャ**:
* **ベースライン（M0–M5）**: 外部LLMに依存しない、完全ローカル・決定論的な高速変換。
* **拡張品質パス（M6–M12 / オプトイン）**: ローカルVLM（Ollama）または各種クラウドモデルを活用した、文書構造の自動認識・スタイル復元・安全なOCR補正。


* **安全性を重視したAI活用**: LLMはセマンティック分類やスタイル推論のみを担当し、最終的なEPUBコード生成や本文の改変は厳密なスキーマとバリデーションにより制御。
* **高速な開発サイクル**: 中間データ（`middle.json`）から直接EPUBをレンダリングする開発コマンドを標準装備。

---

## パイプラインアーキテクチャ

```text
[ 補正済みページ画像 (vFlat 等) ]
               │
               ▼ (自然順序ソート / img2pdf)
[ ロスレス中間 PDF ]
               │
               ▼ (MinerU 3.4.5 Windows GPU / hybrid-engine / effort=high)
[ authoritative middle.json ]
               │
               ├──────────────────────────────────────────┐
               │ [標準パス (M0-M5)]                       │ [拡張品質パス (M6-M12: オプトイン)]
               │ (完全オフライン / 決定論的処理)            │ 
               │                                          ├─ M6: エビデンス収集・セマンティック基盤
               │                                          ├─ M7: LLM Provider抽象化 & 厳格構造化出力
               │                                          ├─ M8: 文書構造・アウトライン調停
               │                                          ├─ M9: 視覚調停 & 安全なOCR補正 (任意/既定OFF)
               │                                          ├─ M10a: スタイルプロファイル推論 (infer)
               │                                          ├─ M11: 日本語組版・空白・箇条書き正規化
               │                                          └─ M10b: 決定論的コンポーネントレンダリング
               ▼                                          │
[ Book2Epub 中間表現 (BookIR) ] ◄─────────────────────────┘
               │
               ▼ (レイアウト意図の再構成)
[ リフロー型 XHTML 5 + MathML + CSS ]
               │
               ▼ (ネイティブパッケージング)
[ EPUBCheck 5.3.0 検証 ]
               │
               ▼
[ 完成した .epub ファイル ]

```

---

## 動作環境

* **OS**: Windows 11 x64（WSL / Docker 不要）
* **Python**: CPython 3.12
* **パッケージマネージャー**: `uv`
* **アクセラレータ**: NVIDIA GPU（RTX 50シリーズ / Blackwell世代を推奨）
* **コア依存関係**:
* MinerU 3.4.5 (PyPI)
* EPUBCheck 5.3.0
* img2pdf
* latex2mathml 3.81.0



---

## クイックスタート

### 1. セットアップ

```powershell
# リポジトリのクローンと環境構築
git clone https://github.com/tratiger/Book2Epub.git
cd Book2Epub
uv sync

```

### 2. 基本変換（標準レガシー互換モード）

外部LLMを使用せず、MinerUの構造抽出とルールベースの正規化のみで安全に変換します。

```powershell
uv run book2epub convert "D:\Books\MyBook\pages" -o "D:\Books\MyBook\MyBook.epub"

```

*デフォルト設定:*

```text
semantic.enabled = false
ocr_correction.mode = off
presentation.mode = legacy

```

### 3. 高品質AIモード（拡張機能）

セマンティック解析やスタイルの自動推論（M6–M12）を有効化する場合に指定します。

**ローカルVLMを利用（Ollama）:**

```powershell
uv run book2epub convert .\pages -o book.epub `
  --semantic `
  --semantic-provider ollama `
  --semantic-model <local-vision-model> `
  --semantic-vision auto `
  --presentation infer

```

**クラウドプロバイダを利用（OpenAI / Gemini / Anthropic）:**

```powershell
$env:OPENAI_API_KEY = "your-api-key"

uv run book2epub convert .\pages -o book.epub `
  --semantic `
  --semantic-provider openai `
  --semantic-model <model-id> `
  --allow-cloud `
  --semantic-vision auto `
  --presentation infer

```

*(※ クラウドモデルの呼び出しには `--allow-cloud` フラグが必須です)*

### 4. 機能ごとの個別指定

セマンティック解析を行わずに、特定機能のみを組み合わせて実行することも可能です。

```powershell
# 構造は維持したまま、元本のスタイル推論のみ適用
uv run book2epub convert .\pages -o book.epub `
  --no-semantic `
  --semantic-provider ollama `
  --semantic-model <local-vision-model> `
  --presentation infer

# OCR誤認識の安全な修正のみ適用
uv run book2epub convert .\pages -o book.epub `
  --no-semantic `
  --semantic-provider ollama `
  --semantic-model <local-vision-model> `
  --ocr-correction safe `
  --presentation enhanced

```

### 5. 開発・検証コマンド

MinerUの重いGPU推論ステップをスキップし、既存の中間JSONからレンダラ・パッケージング処理のみを即座に再実行します。

```powershell
uv run book2epub from-middle ".work\jobs\<job-id>\mineru\book_middle.json" -o out.epub

```

---

## 主要なCLIオプション

| オプション | 指定値 | 説明 |
| --- | --- | --- |
| `--semantic` / `--no-semantic` | boolean | LLMによる高度な文書構造認識・階層調停の有効/無効。 |
| `--presentation` | `legacy` / `enhanced` / `infer` | デザイン適用モード。`legacy`（標準CSS）、`enhanced`（高品位CSS）、`infer`（原本画像からスタイルを自動判定）。 |
| `--ocr-correction` | `off` / `safe` / `all` | OCR誤字脱字補正。既定は `off`。`safe` は本文散文のみ視覚根拠に基づき補正。数式は常に不変。 |
| `--semantic-provider` | `ollama` / `openai` / `google` / `anthropic` | canonical provider。CLIでは`gemini`も`google`のaliasとして利用可能。 |
| `--semantic-model` | `<model-id>` | 使用するモデル識別子。特定モデル名には依存しない。 |
| `--semantic-vision` | `off` / `auto` / `on` | canonical visual policy。CLIでは`always`も`on`のaliasとして利用可能。 |
| `--allow-cloud` | flag | 外部クラウドAPIへのデータ送信を明示的に許可。 |

---

## 設計原則・非交渉ルール

本プロジェクトでは、品質・安定性・再現性を担保するため以下の設計を厳格に排除しています。

* **固定レイアウトおよび画像オーバーレイの禁止**: 全面スキャン画像を背景にしてOCRテキストを重ねる手法や、絶対座標（Absolute Positioning）によるページ再現は行いません。
* **Pandoc の不採用**: EPUB 3.3パッケージングおよびXHTML整形は内製エンジンで厳密に制御します。
* **中間データの単一情報源（Single Source of Truth）**: 認識データは MinerU の `*_middle.json` のみを採用し、`content_list.json` や Markdown への依存を排除しています。
* **勝手な本文改変の防止**: LLMは分類や属性推論（セマンティクス・階層構造・CSSプロファイル）のみを決定し、勝手な文章生成・置換を行えない構造化出力スキーマを採用しています。
* **数式データの不変性**: OCR補正が有効な場合でも、抽出されたLaTeX/MathML数式データは変更されません。
* **コンテナフリー**: 開発・本番ともにWSLやDockerを不要とし、Windows環境上で完結します。

---

## プロジェクト構成とマイルストーン

実装および仕様の詳細については、各マイルストーン仕様書を参照してください。

```text
├── 00_PRODUCT_AND_ARCHITECTURE.md        # コアアーキテクチャ規約
├── AGENTS.md                             # 開発・実装エージェント行動規範
├── BASELINE_CODE_AUDIT.md                # 実装ベースライン監査記録
│
├── milestones/                           # 各フェーズの実装マイルストーン
│   ├── M0_FOUNDATION.md                  # 基盤環境・ロギング・共通IR
│   ├── M1_INGEST_AND_MINERU.md           # 画像取り込み・PDF化・MinerU実行
│   ├── M2_MIDDLE_JSON_TO_BOOKIR.md       # middle.json の BookIR 正規化
│   ├── M3_REFLOW_RENDERER.md             # リフローXHTML/MathMLレンダラ
│   ├── M4_EPUB_PACKAGE_AND_VALIDATION.md # EPUBパッケージング・EPUBCheck
│   ├── M5_QA_RELIABILITY_AND_RELEASE.md  # 信頼性試験・リリースゲート
│   ├── M6_SEMANTIC_FOUNDATION_AND_EVIDENCE.md
│   ├── M7_LLM_PROVIDERS_AND_STRUCTURED_OUTPUTS.md
│   ├── M8_DOCUMENT_STRUCTURE_AND_SEMANTIC_ADJUDICATION.md
│   ├── M9_VISUAL_ARBITRATION_AND_OPTIONAL_OCR_CORRECTION.md
│   ├── M10_PRESENTATION_RECONSTRUCTION_AND_COMPONENTS.md
│   ├── M11_TYPOGRAPHY_WHITESPACE_AND_LIST_NORMALIZATION.md
│   └── M12_QA_EVALUATION_AND_RELEASE.md
│
└── appendices/                           # 技術詳細・スキーマ定義・外部規格 (A〜O)

```
