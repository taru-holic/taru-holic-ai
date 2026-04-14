# -*- coding: utf-8 -*-
import streamlit as st
import anthropic
import os
import requests
import base64
import io
from datetime import datetime, timedelta
from pypdf import PdfReader

# ページ設定
st.set_page_config(page_title="TARU HOLIC AI", page_icon="🛢️", layout="wide")

# APIキー（Streamlit Cloudではsecretsから取得）
try:
    API_KEY = st.secrets["ANTHROPIC_API_KEY"].strip()
except:
    API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

try:
    SHOPIFY_TOKEN = st.secrets["SHOPIFY_ACCESS_TOKEN"].strip()
except:
    SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN", "").strip()

SHOP = "wake-up-wine-japan.myshopify.com"
SHOPIFY_HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}

# APIキーチェック
if not API_KEY:
    st.error("ANTHROPIC_API_KEY が設定されていません")
    st.stop()

client = anthropic.Anthropic(api_key=API_KEY)

# Shopify関数
def get_shopify_sales(days=1):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00+09:00")
    url = f"https://{SHOP}/admin/api/2024-01/orders.json"
    params = {"status": "any", "created_at_min": since, "limit": 250,
              "fields": "id,created_at,total_price,financial_status,line_items"}
    response = requests.get(url, headers=SHOPIFY_HEADERS, params=params)
    return response.json().get("orders", [])

def get_sales_summary():
    result = []
    for label, days in [("本日", 1), ("直近7日", 7), ("直近30日", 30)]:
        orders = get_shopify_sales(days)
        total, count, products = 0, 0, {}
        for order in orders:
            if order.get("financial_status") in ["paid", "partially_paid"]:
                total += float(order.get("total_price", 0))
                count += 1
                for item in order.get("line_items", []):
                    name = item.get("title", "不明")
                    qty = item.get("quantity", 0)
                    price = float(item.get("price", 0)) * qty
                    if name in products:
                        products[name]["qty"] += qty
                        products[name]["price"] += price
                    else:
                        products[name] = {"qty": qty, "price": price}
        result.append(f"【{label}】注文{count}件 / 売上¥{total:,.0f}")
        for name, data in sorted(products.items(), key=lambda x: x[1]["price"], reverse=True)[:5]:
            result.append(f"  {name}：{data['qty']}個 / ¥{data['price']:,.0f}")
    return "\n".join(result)

# エージェント定義
ORCHESTRATOR_PROMPT = """
あなたはTARU HOLICの事業参謀オーケストレーターです。必ず日本語で回答してください。
ユーザーの依頼を受け取り、以下の専門エージェントのどれに振り分けるかを判断し、エージェント名だけを返してください。

エージェント一覧：
- creative: コピー・LP・Makuake・修正フィードバック
- product: 新商品判断・ヒーロー vs コモディティ分類
- channel: Amazon/楽天/Shopify/Makuakeの戦略
- finance: 価格・利益・資金繰り・在庫・売上データ・注文数
- brand: ブランドの判断・世界観の確認
- cx: 同梱物・FAQ・顧客体験
- hr: 採用・外注の評価

例：creative または creative,brand
"""

AGENTS = {
    "creative": """あなたはTARU HOLICのブランド編集者兼クリエイティブディレクターです。必ず日本語で回答。
TARU HOLICとは：「時間と変化を楽しむ、知的体験ブランド」一行定義：「味わいを、育てる」
コピーの原則：良い＝上質・短い・余白がある・知的・感情価値 / NG＝安売り感・超すごい系・通販調・説明しすぎ
修正フィードバック出力：1.ブランドとのズレを指摘 2.修正案3案 3.ニュアンス差説明 4.最推奨案と理由""",

    "product": """あなたはTARU HOLICの商品企画責任者です。必ず日本語で回答。
新商品評価：STEP1:ヒーロー/コモディティ分類 STEP2:本質適合（熟成/燻製/香り/木/時間/儀式性/所有欲/大人の趣味性）
STEP3:変化・再利用・研究性 STEP4:写真とコピーだけで欲しくさせられるか STEP5:チャネル STEP6:ブランド希釈リスク""",

    "channel": """あなたはTARU HOLICのEC戦略担当です。必ず日本語で回答。
チャネル別思想：Makuake＝物語と応援購入・限定性 / Amazon＝需要・検索・比較優位 / 楽天＝キーワード・ポイント / Shopify＝ブランド体験の本丸""",

    "finance": """あなたはTARU HOLICの財務・在庫担当です。必ず日本語で回答。
【重要】あなたはShopifyの実売上データにアクセスできます。「実際のShopify売上データ」が添付されている場合、本物のリアルタイムデータです。
価格提案：ブランド価値・原価・粗利・CV・見え方を同時に。値上げ・アップセル・セット化余地を確認。
在庫判断：1ヶ月未満でアラート / 季節補正 / リードタイム考慮""",

    "brand": """あなたはTARU HOLICのブランド番人です。必ず日本語で回答。
ブランド定義：「時間と変化を楽しむ、知的体験ブランド」
チェック：ヒーロー/コモディティ混同なし？安っぽくない？世界観から外れていない？""",

    "cx": """あなたはTARU HOLICのCX設計者です。必ず日本語で回答。
同梱物の思想：「説明書ではなく小さなブランドブック」
必須要素：所有の喜び・使い方・楽しみ方・応用・「もっと試したい」導線""",

    "hr": """あなたはTARU HOLICの採用補佐です。必ず日本語で回答。
重視：実行力・レス速さ・締切遵守・素直さ・泥臭い業務OK
避けたい：口だけ戦略型・納期曖昧・連絡遅い"""
}

AGENT_NAMES = {
    "creative": "クリエイティブ", "product": "商品戦略", "channel": "チャネル戦略",
    "finance": "財務・在庫", "brand": "ブランドガード", "cx": "同梱物・CX", "hr": "採用・外注"
}

def route(user_input):
    response = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=50,
                                       system=ORCHESTRATOR_PROMPT,
                                       messages=[{"role": "user", "content": user_input}])
    return response.content[0].text.strip()

def call_agent(agent_key, user_input):
    prompt = AGENTS.get(agent_key)
    if not prompt:
        return None
    sales_keywords = ["売上", "注文", "販売", "売れ", "データ", "実績", "shopify", "ショッピファイ"]
    enhanced_input = user_input
    if any(kw in user_input.lower() for kw in sales_keywords):
        try:
            sales_data = get_sales_summary()
            enhanced_input = f"{user_input}\n\n【実際のShopify売上データ】\n{sales_data}"
        except:
            pass
    response = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=2000,
                                       system=prompt,
                                       messages=[{"role": "user", "content": enhanced_input}])
    return response.content[0].text

# 画像・PDF処理関数
def process_image(uploaded_file):
    """画像をbase64エンコード"""
    bytes_data = uploaded_file.getvalue()
    base64_image = base64.b64encode(bytes_data).decode("utf-8")
    media_type = uploaded_file.type
    return base64_image, media_type

def process_pdf(uploaded_file):
    """PDFからテキストを抽出"""
    pdf_reader = PdfReader(io.BytesIO(uploaded_file.getvalue()))
    text = ""
    for page in pdf_reader.pages[:10]:  # 最大10ページ
        text += page.extract_text() + "\n"
    return text[:5000]  # 最大5000文字

def call_agent_with_image(agent_key, user_input, image_data, media_type):
    """画像付きでエージェントを呼び出し"""
    prompt = AGENTS.get(agent_key)
    if not prompt:
        return None

    messages = [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
            {"type": "text", "text": user_input}
        ]
    }]

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        system=prompt,
        messages=messages
    )
    return response.content[0].text

# UI
st.title("🛢️ TARU HOLIC AI")
st.caption("マルチエージェントシステム｜クリエイティブ / 商品戦略 / チャネル / 財務・在庫 / ブランド / CX / 採用")

# サイドバー
with st.sidebar:
    st.header("📊 売上ダッシュボード")
    if st.button("売上を更新"):
        with st.spinner("取得中..."):
            try:
                st.text(get_sales_summary())
            except Exception as e:
                st.error(f"エラー: {e}")

    st.divider()
    st.header("📎 ファイルアップロード")
    uploaded_file = st.file_uploader(
        "画像またはPDFをアップロード",
        type=["png", "jpg", "jpeg", "gif", "webp", "pdf"]
    )
    if uploaded_file:
        if uploaded_file.type == "application/pdf":
            st.success(f"PDF: {uploaded_file.name}")
        else:
            st.image(uploaded_file, caption=uploaded_file.name, width=200)

# メインチャット
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("質問を入力してください"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("考え中..."):
            agents = route(prompt)
            agent_keys = [a.strip() for a in agents.split(",")]
            full_response = ""

            for key in agent_keys:
                name = AGENT_NAMES.get(key, key)

                # ファイルがアップロードされている場合
                if uploaded_file:
                    if uploaded_file.type == "application/pdf":
                        # PDF: テキスト抽出して追加
                        pdf_text = process_pdf(uploaded_file)
                        enhanced_prompt = f"{prompt}\n\n【添付PDFの内容】\n{pdf_text}"
                        result = call_agent(key, enhanced_prompt)
                    else:
                        # 画像: Vision APIで処理
                        image_data, media_type = process_image(uploaded_file)
                        result = call_agent_with_image(key, prompt, image_data, media_type)
                else:
                    result = call_agent(key, prompt)

                if result:
                    full_response += f"**【{name}エージェント】**\n\n{result}\n\n---\n\n"

            st.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})
