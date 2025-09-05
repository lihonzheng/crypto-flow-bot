#!/usr/bin/env python3
import os, datetime as dt, requests, tweepy, dateutil.parser as dp
from dateutil.tz import tzutc

NOW         = dt.datetime.now(tzutc())
CQ_BASE     = "https://api.coinmetrics.io/v4"
WHALE_TW    = "whale_alert"          # Whale Alert 推特账号
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID     = os.getenv("TELEGRAM_CHAT_ID")

# ---------- 0. 工具 ----------
def tg_send(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})

# ---------- 1. CryptoQuant 免费层 ----------
def cq_metric(metric, asset="btc", days=3):
    """拉取 coinmetrics 开放 API（无需 key）"""
    end = NOW.strftime("%Y-%m-%d")
    start = (NOW - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    url = f"{CQ_BASE}/timeseries/asset-metrics?assets={asset}&metrics={metric}&start={start}&end={end}&frequency=1d"
    r = requests.get(url, timeout=15).json()
    if "data" not in r:
        return None
    return [float(x["values"][0]) for x in r["data"]]

# ---------- 2. Whale Alert 推特 ----------
def whale_tweets_hours(hours=24):
    """用 nitter 镜像免登录拉取推文（公开）"""
    nitter = "https://nitter.net"
    url = f"{nitter}/{WHALE_TW}/rss"
    rss = requests.get(url, timeout=15).text
    import xml.etree.ElementTree as ET
    items = ET.fromstring(rss).findall(".//item")
    cutoff = NOW - dt.timedelta(hours=hours)
    tweets = []
    for it in items:
        t = dp.parse(it.find("pubDate").text)
        if t < cutoff:
            continue
        tweets.append(it.find("title").text)
    return tweets

def parse_whale(tweets):
    """过滤 >50M USD 且 流入交易所 的 BTC/ETH/USDT"""
    flag_words = ["transferred to", "to #coinbase", "to #binance", "to #kraken", "to #bitfinex"]
    coins = ["BTC", "ETH", "USDT"]
    out = []
    for t in tweets:
        if not any(w in t for w in flag_words):
            continue
        try:
            usd = float(t.split("USD")[0].split("(")[-1].replace(",", ""))
            if usd >= 50_000_000 and any(c in t for c in coins):
                out.append(t)
        except Exception:
            continue
    return out

# ---------- 3. 生成日报 ----------
def build_report():
    # 1. BTC 交易所净流量（3 日累计）
    flows = cq_metric("FlowOutExNtv", "btc", 3)  # 流出为正值
    if flows:
        net3d = -sum(flows) / 1e8  # 转为净流出（负值=流出）
        btc_flow_text = f"🔍 BTC 交易所净流量（3日）\n<code>{net3d:+.1f} BTC</code> " + \
                        ("✅ 持续流出（看涨）" if net3d < -5000 else "⚠️ 波动不大" if -5000 <= net3d <= 5000 else "🔴 持续流入（看跌）")
    else:
        btc_flow_text = "🔍 BTC 交易所净流量（3日）\n⚠️ 数据缺失"

    # 2. USDT 交易所余额 24h 变动（粗略用链上供应量 proxy）
    usdt_sup = cq_metric("SupplyNtv", "usdt", 1)
    if usdt_sup and len(usdt_sup) >= 2:
        delta = (usdt_sup[-1] - usdt_sup[-2]) / 1e6
        usdt_text = f"💰 USDT 交易所余额变动（24h）\n<code>{delta:+.1f} M</code> " + \
                    ("✅ 大幅流入（看涨）" if delta > 500 else "🔴 大幅流出（看跌）" if delta < -500 else "⚠️ 变动不大")
    else:
        usdt_text = "💰 USDT 交易所余额变动（24h）\n⚠️ 数据缺失"

    # 3. Whale Alert
    whale_in = parse_whale(whale_tweets_hours(24))
    whale_text = "🐋 大额流入交易所（>50M USD）\n" + \
                 ("\n".join(whale_in) if whale_in else "今日无异常大额流入")

    # 4. 结论
    bullish_score = 0
    if "持续流出" in btc_flow_text: bullish_score += 1
    if "大幅流入" in usdt_text: bullish_score += 1
    if not whale_in: bullish_score += 1
    summary = "📈 综合结论：<b>看涨组合成立，短线谨慎看多</b>" if bullish_score >= 2 else \
              "⚠️ 多空信号混杂，建议观望" if bullish_score == 1 else \
              "📉 下跌风险加大，谨慎"

    report = f"📊 <b>币圈资金流向日报</b>  {NOW.strftime('%Y-%m-%d')}\n\n" \
             f"{btc_flow_text}\n\n{usdt_text}\n\n{whale_text}\n\n{summary}"
    return report

# ---------- 4. 主入口 ----------
if __name__ == "__main__":
    try:
        tg_send(build_report())
    except Exception as e:
        tg_send(f"⚠️ 日报生成失败：{e}")