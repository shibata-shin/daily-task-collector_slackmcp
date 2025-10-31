import os
import json
from datetime import datetime, timedelta
from anthropic import Anthropic
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# 環境変数から認証情報を取得
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
SLACK_USER_TOKEN = os.environ.get("SLACK_USER_TOKEN")  # User Token (xoxp-)

client = Anthropic(api_key=ANTHROPIC_API_KEY)
slack_client = WebClient(token=SLACK_USER_TOKEN)

def get_my_user_id():
    """自分のユーザーIDを取得"""
    try:
        response = slack_client.auth_test()
        return response["user_id"]
    except SlackApiError as e:
        print(f"ユーザーID取得エラー: {e.response['error']}")
        return None

def get_mentions_last_24h(user_id):
    """過去24時間の自分宛メンションを取得"""
    try:
        # 24時間前のタイムスタンプ
        oldest = (datetime.now() - timedelta(hours=24)).timestamp()
        
        # 自分へのメンションを検索
        result = slack_client.search_messages(
            query=f"<@{user_id}>",
            sort="timestamp",
            sort_dir="desc",
            count=100
        )
        
        mentions = []
        for match in result["messages"]["matches"]:
            msg_timestamp = float(match["ts"])
            if msg_timestamp >= oldest:
                mentions.append({
                    "text": match["text"],
                    "user": match.get("username", "Unknown User"),
                    "channel": match.get("channel", {}).get("name", "Unknown Channel"),
                    "timestamp": match["ts"],
                    "permalink": match.get("permalink", "")
                })
        
        return mentions
    
    except SlackApiError as e:
        print(f"Slack API Error: {e.response['error']}")
        return []

def analyze_with_claude(mentions):
    """Claudeでメンションをタスクとして分析・整理"""
    if not mentions:
        return "過去24時間にメンションはありませんでした。"
    
    # メンション情報をテキストに整形
    mentions_text = "\n\n".join([
        f"【{i+1}】\n"
        f"投稿者: {m['user']}\n"
        f"チャンネル: #{m['channel']}\n"
        f"内容: {m['text']}\n"
        f"リンク: {m['permalink']}"
        for i, m in enumerate(mentions)
    ])
    
    prompt = f"""以下は過去24時間にSlackで私宛にメンションされた投稿です。
これらをタスクとして分析し、以下の形式で整理してください：

## 🔴 緊急度高・重要度高（今日中に対応）

## 🟡 緊急度中・重要度高（今週中に対応）

## 🟢 緊急度低・重要度中（来週以降でOK）

## ⚪ 情報共有のみ（対応不要）

各タスクには以下を含めてください：
- タスク概要（簡潔に）
- 誰からの依頼か
- どのチャンネルか
- リンク

---

メンション内容：
{mentions_text}
"""
    
    try:
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        return message.content[0].text
    
    except Exception as e:
        print(f"Claude API Error: {e}")
        return "タスクの分析中にエラーが発生しました。"

def send_dm_to_self(organized_tasks, user_id):
    """整理したタスクを自分にDMで送信（User Tokenで自分にメッセージ）"""
    try:
        # User Tokenを使う場合、自分とのDMチャンネルを開く
        response = slack_client.conversations_open(users=[user_id])
        dm_channel_id = response["channel"]["id"]
        
        # メッセージを送信
        timestamp = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        message = f"📋 *タスク整理レポート* ({timestamp})\n\n{organized_tasks}"
        
        slack_client.chat_postMessage(
            channel=dm_channel_id,
            text=message,
            mrkdwn=True
        )
        
        print("✅ DMの送信に成功しました")
        
    except SlackApiError as e:
        print(f"DM送信エラー: {e.response['error']}")

def main():
    """メイン処理"""
    print("👤 ユーザー情報を取得中...")
    user_id = get_my_user_id()
    if not user_id:
        print("❌ ユーザーIDの取得に失敗しました")
        return
    
    print(f"✅ User ID: {user_id}")
    
    print("🔍 過去24時間のメンションを取得中...")
    mentions = get_mentions_last_24h(user_id)
    print(f"📊 {len(mentions)}件のメンションを検出")
    
    print("🤖 Claudeでタスクを分析中...")
    organized_tasks = analyze_with_claude(mentions)
    
    print("📤 整理したタスクをDMで送信中...")
    send_dm_to_self(organized_tasks, user_id)
    
    print("✨ 完了しました！")

if __name__ == "__main__":
    main()
