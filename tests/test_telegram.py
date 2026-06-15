from zuse.telegram import TelegramSettings, extract_text_message


def test_extract_text_message():
    update = {
        "update_id": 42,
        "message": {
            "message_id": 7,
            "text": " hello ",
            "chat": {"id": 123},
            "from": {"id": 456, "username": "nik"},
        },
    }

    msg = extract_text_message(update)

    assert msg is not None
    assert msg.update_id == 42
    assert msg.message_id == 7
    assert msg.chat_id == 123
    assert msg.sender_id == 456
    assert msg.text == "hello"
    assert msg.username == "nik"


def test_extract_text_message_ignores_non_text():
    assert extract_text_message({"update_id": 1, "message": {"photo": []}}) is None


def test_extract_text_message_ignores_bots():
    update = {
        "update_id": 1,
        "message": {
            "message_id": 2,
            "text": "hi",
            "chat": {"id": 3},
            "from": {"id": 4, "is_bot": True},
        },
    }

    assert extract_text_message(update) is None


def test_telegram_settings_from_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ZUSE_TELEGRAM_ALLOWED_CHAT_IDS", "123, -456")

    settings = TelegramSettings.from_env()

    assert settings.bot_token == "token"
    assert settings.allowed_chat_ids == (123, -456)
