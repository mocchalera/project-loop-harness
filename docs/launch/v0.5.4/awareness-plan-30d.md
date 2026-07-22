# PLH v0.5.4認知拡大30日計画

**期間:** 2026-07-23〜2026-08-21

**PCL:** Goal `G-0066`; campaign Task `T-0136`

**選択:** Cockpit Ask `ask_00c0f7319a0b` / Decision `DEC-0008`

**主成果:** 認知拡大

**権限境界:** 外部投稿・個別連絡は、完成文案・送信先・タイミングを
提示し、毎回human approvalを得てから実行する。この計画自体は外部
公開を許可しない。

## 1. 今の位置

PLH v0.5.4はGitHub ReleaseとPyPIで公開済みで、ローカル、モデル中立、
Evidence中心のcontrol planeとしての製品境界は整っている。ただし、
公開面での発見と第三者の具体的な反応はまだ小さい。

2026-07-23 01:54 JSTのGitHub API基準値:

| 指標 | 基準値 | 扱い |
| --- | ---: | --- |
| Stars | 0 | 補助的な関心シグナル |
| Forks | 0 | 補助的な行動シグナル |
| Open issues | 0 | 質問・不具合・要望の公開受付 |
| Watchers | 0 | 補助的な継続関心シグナル |
| Views, 14 days | 27 / 4 unique | 公開後の14日rolling windowと比較 |
| Clones, 14 days | 899 / 192 unique | CI・bot・toolingを含み得るためKPIに使わない |

Clones、views、downloadsは利用者数やadoption証明ではない。この計画は、
利用者数の未検証claimを作らない。

## 2. 誰に何を伝えるか

主対象:

- Codex、Claude Code等で複数の開発作業を回すoperator;
- agentの完了報告をreviewするmaintainer・tech lead;
- local-first、監査可能性、human gateを重視する開発者。

一文の価値:

> PLHは、coding agentの「done」を、レビュー可能なEvidence・残存リスク・
> 再開可能な次の一手に変えるlocal control plane。

繰り返すメッセージは3つに限定する:

1. 完了を主張ではなくEvidenceにする。
2. 安全な定型作業はagentが続け、本物のhuman decisionで止まる。
3. SQLite・JSONL・生成dashboardを分け、ローカルに状態と監査履歴を残す。

## 3. 30日の成功条件

主KPI:

- 異なる人から、内容のあるqualified reactionを3件得る。

qualified reactionとは、PLHの問題設定・導入・Evidence・安全境界のいずれかに
ついて、具体的な質問、再現報告、利用意向、不具合、改善要望がある反応を
指す。like、impression、無言のstarだけは含めない。

補助KPI:

- GitHubの14日rolling unique visitorsがいずれかの窓で20以上;
- GitHub starsが5以上;
- 第三者から初回利用の具体的な報告を1件以上;
- 各投稿のimpressions・link clicks・反応を、取得できる範囲で記録。

数値目標はコンテンツ改善の判断材料であり、外部adoptionのclaimではない。

## 4. 週別実行計画

### Week 1 — 入口と第1告知

- READMEの旧v0.5.2 Adoption Proofをversion-neutralなproof boundaryへ修正;
- v0.5.4 X文案 `E-0587`を正確な本文と宛先付きで公開承認へ提出;
- 承認時のみXに投稿し、URL・時刻・approval receiptを記録;
- 24時間・72時間の反応とGitHub trafficをスナップショット化。

### Week 2 — 問題起点の技術コンテンツ

- 「agentの完了報告をどうやって信じるか」を起点に、日本語の技術記事または
  X threadを作成;
- `pcl start → finish → completion packet → next`を一つの再現可能な例で示す;
- 公開前に本文・チャネル・タイミングを別途承認。

### Week 3 — 動く証拠

- 3-minute demoの実行結果から、完了パケットとdashboardがどう繋がるかを
  1枚画像または短いclipにする;
- 全CLIの紹介ではなく、「doneを証拠に変える」一動線だけを見せる;
- 公開前にmedia・alt text・本文・宛先を別途承認。

### Week 4 — 反応を次の一手に変える

- qualified reactionを理解・導入・安全・不具合・要望に分類;
- 一番強い学びを、ドキュメント改善または次のコンテンツに一つだけ反映;
- 初回利用の申し出があれば、個別連絡・観察の承認を改めて取る;
- Day 30にcontinue / revise / stopをPCL Decisionとして記録。

## 5. チャネルの役割

| チャネル | 役割 | 今回の境界 |
| --- | --- | --- |
| GitHub README | 認知を理解・導入へ変える着地面 | 内部修正とcommitは実行する; pushは別承認 |
| X | 新リリースと一文価値の発見 | 文案固定済み; 投稿は別承認 |
| Zenn | 問題起点の詳細説明と検索可能な資産 | 既存v0.5.0記事あり; 新規公開は別承認 |
| Reddit | 英語圏の具体的な問題コミュニティ | Week 1では実行しない; subredditごとに別承認 |
| Hacker News | 使わない | AI生成・編集文の投稿禁止境界により対象外 |

チャネルの同時多発は避け、原則は週2回以下の外部投稿とする。

## 6. 観測・Evidence契約

各公開アクションで以下を残す:

```text
Action ID:
Channel and URL:
Approved exact-copy path and SHA-256:
Approval source/reference:
Posted by:
Posted at:
24h native metrics:
72h native metrics:
Qualified reactions:
GitHub 14-day traffic snapshot:
Decision for next action:
```

週次snapshotはこの計画ファイルを書き換えず、新規の日付付きartifactとして
追加する。Evidence登録済みファイルはwrite-onceとする。スクリーンショット、
非公開メッセージ、個人情報は、必要性と同意なしに保存しない。

## 7. 停止条件

以下のどれかで次の公開を止める:

- GitHub・PyPI・READMEのバージョンやインストール手順が不一致;
- セキュリティ、privacy、認証情報、破壊的操作の懸念;
- 外部adoption、利用者数、比較優位の未検証claim;
- 投稿先の自己宣伝・AI生成コンテンツ規約との不整合;
- 同一の誤解やblockerが2件以上。

## 8. すぐ実行する順序

1. READMEのproof boundaryをv0.5.4基準に修正する。
2. この30日計画をcopied Evidenceとして固定する。
3. `E-0587`のX文案について、正確な本文・宛先・実行範囲のhuman approvalを得る。
4. 承認時のみ投稿し、24時間と72時間の観測Taskを開始する。

## Current status

- README proof boundary: prepared locally;
- 30-day plan: prepared locally;
- X draft: `E-0587`, selected but not posted;
- external post or message: none performed by this plan.
