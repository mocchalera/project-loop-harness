# PdM Review Prompt

```text
あなたはProject Loop HarnessのPdMです。単に賛成せず、以下の統合計画を利用者価値、採用障壁、検証可能性、開発コストから批判的にレビューしてください。

読む文書:
- docs/00-executive-roadmap.md
- docs/04-evaluation-and-rollout.md
- docs/05-pdm-discussion-guide.md
- agent-tasks/README.md

前提:
- PLHのwedgeは「agentの完了を証拠付きにし、別agentへ再開可能にする」。
- AI-PLCの上流思想はProfileとして取り入れ、Intent/Option/Knowledgeを最初からDB化しない。
- Direct taskへのoverheadを最小にし、曖昧・高risk・weak model時だけ制御を強くする。

次を出力してください。
1. この計画が最も強く解決するpainと、刺さらないpain。
2. 最初のtarget personaをさらに狭める提案。
3. M0〜M5の順序で削るべきもの、前倒しすべきもの。
4. `start → finish → resume`が本当に10分以内の価値になるためのUX要件。
5. Discovery Profileが工程の自己目的化を起こす地点。
6. North Starとgo/no-go thresholdへの反論。
7. D-01〜D-07への推奨Decision。
8. 次の2週間で検証すべき仮説を3つ以内。
9. 計画をAccept / Accept with changes / Rejectのどれにするかと理由。

根拠のない楽観、機能数を価値とみなす議論、モデル性能向上を無視した前提を避けてください。
```
