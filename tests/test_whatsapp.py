import hashlib
import hmac

from zuse.whatsapp import (
    WWEBJS_PACKAGE_JSON,
    WWEBJS_RUNNER,
    WhatsAppSettings,
    WhatsAppWebSession,
    build_arg_parser,
    extract_text_messages,
    normalize_phone,
    verify_meta_signature,
)


def test_extract_text_messages_ignores_statuses_and_non_text():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid.1",
                                    "from": "+49 170 123456",
                                    "type": "text",
                                    "text": {"body": " Hallo Zuse "},
                                },
                                {"id": "wamid.2", "from": "49170", "type": "image"},
                            ],
                            "statuses": [{"id": "wamid.old", "status": "sent"}],
                        }
                    }
                ]
            }
        ]
    }

    messages = extract_text_messages(payload)

    assert len(messages) == 1
    assert messages[0].message_id == "wamid.1"
    assert messages[0].sender == "49170123456"
    assert messages[0].text == "Hallo Zuse"


def test_verify_meta_signature():
    body = b'{"hello":"world"}'
    secret = "topsecret"
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert verify_meta_signature(body, signature, secret)
    assert not verify_meta_signature(body, "sha256=bad", secret)
    assert verify_meta_signature(body, None, "")


def test_arg_parser_defaults_to_qr_mode():
    args = build_arg_parser().parse_args([])

    assert args.mode == "qr"
    assert args.auto is True


def test_whatsapp_web_session_reuses_same_agent():
    class FakeAgent:
        def __init__(self):
            self.turns = []

        def run_turn(self, text):
            self.turns.append(text)
            return f"reply {len(self.turns)}"

    agent = FakeAgent()
    session = WhatsAppWebSession(agent, allowed_sender="49170")

    assert session.handle_message("1", "49170@c.us", "eins") == "reply 1"
    assert session.handle_message("2", "49170@c.us", "zwei") == "reply 2"
    assert agent.turns == ["eins", "zwei"]


def test_whatsapp_web_session_blocks_other_senders():
    class FakeAgent:
        def run_turn(self, text):  # pragma: no cover - must not be called
            raise AssertionError(text)

    session = WhatsAppWebSession(FakeAgent(), allowed_sender="49170")

    assert "nicht freigeschaltet" in session.handle_message("1", "49171@c.us", "hallo")


def test_qr_runner_uses_wppconnect_dependency_and_local_http_session():
    assert "@wppconnect-team/wppconnect" in WWEBJS_PACKAGE_JSON
    assert "postJson('/message'" in WWEBJS_RUNNER


def test_qr_runner_listens_to_self_chat_messages_without_reply_loop():
    assert "client.onAnyMessage" in WWEBJS_RUNNER
    assert "isOwnSelfChatMessage" in WWEBJS_RUNNER
    assert "zuseReplyMarker" in WWEBJS_RUNNER


def test_settings_from_env_normalizes_allowed_senders(monkeypatch):
    monkeypatch.setenv("ZUSE_WHATSAPP_VERIFY_TOKEN", "verify")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "access")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "phone")
    monkeypatch.setenv("ZUSE_WHATSAPP_ALLOWED_SENDERS", "+49 170 1,49172")

    settings = WhatsAppSettings.from_env()

    assert settings.verify_token == "verify"
    assert settings.access_token == "access"
    assert settings.phone_number_id == "phone"
    assert settings.allowed_senders == ("491701", "49172")
    assert normalize_phone("+49 170 1") == "491701"
