# 流動性枯渇予兆ダッシュボード

レポ市場・信用市場・銀行システム・円キャリーの4層で金融危機の予兆を監視するダッシュボード。

## 使い方

### ローカル実行
```bash
pip install -r requirements.txt
streamlit run app.py
```

### Streamlit Cloud
1. このリポジトリをフォーク
2. [Streamlit Cloud](https://streamlit.io/cloud) でデプロイ
3. Secrets に `FRED_API_KEY = "your_key"` を設定（任意）

## データソース
- [FRED（セントルイス連銀）](https://fred.stlouisfed.org)
- [CFTC](https://publicreporting.cftc.gov)

## 作成
[neco3](https://note.com/mofuneco)
