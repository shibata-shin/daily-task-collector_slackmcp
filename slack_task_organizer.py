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
    
    # メンション情報をテキストに整形（簡潔に）
    mentions_text = "\n\n".join([
        f"[{i+1}] {m['user']} in #{m['channel']}\n{m['text']}"
        for i, m in enumerate(mentions)
    ])
    
    prompt = f"""以下は過去24時間にSlackで私宛にメンションされた投稿です。
これらをタスクとして分析し、以下の形式で整理してください：

*🔴 緊急度高・重要度高（今日中）*

*🟡 緊急度中・重要度高（今週中）*

*🟢 緊急度低・重要度中（来週以降）*

*⚪ 情報共有のみ（対応不要）*

各タスクは以下の形式で1行にまとめてください：
• タスク概要 (依頼者名 / #チャンネル名)

重要な注意事項：
- 見出し以外に太字（**）や装飾は使わない
- 各タスクは1行で簡潔に
- リンクは省略（必要なら元メッセージから確認可能）
- 箇条書きは「•」のみ使用
- 全体を2000文字以内に収める

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
        
        # メッセージを送信（Slackの制限: 40,000文字だが、安全のため3,900文字で分割）
        timestamp = datetime.now().strftime("%Y/%m/%d %H:%M")
        header = f"📋 タスク整理レポート ({timestamp})\n\n"
        
        max_length = 3900
        messages = []
        
        if len(organized_tasks) <= max_length:
            messages.append(header + organized_tasks)
        else:
            # 緊急度ごとに分割して送信
            sections = organized_tasks.split('\n\n')
            current_message = header
            
            for section in sections:
                if len(current_message) + len(section) + 2 <= max_length:
                    current_message += section + "\n\n"
                else:
                    messages.append(current_message.strip())
                    current_message = section + "\n\n"
            
            if current_message.strip():
                messages.append(current_message.strip())
        
        # メッセージを順次送信
        for i, msg in enumerate(messages):
            if i > 0:
                # 2つ目以降のメッセージには続きであることを示す
                msg = f"（続き {i+1}/{len(messages)}）\n\n" + msg
            
            slack_client.chat_postMessage(
                channel=dm_channel_id,
                text=msg,
                mrkdwn=True,
                unfurl_links=False,  # リンクプレビューを無効化
                unfurl_media=False
            )
        
        print(f"✅ DMの送信に成功しました（{len(messages)}件）")
        
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
