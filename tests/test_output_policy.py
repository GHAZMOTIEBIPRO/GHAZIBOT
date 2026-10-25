"""Per-source, per-use rights with default deny; private Telegram only to a verified private chat."""
from types import SimpleNamespace

from options_radar import output_policy as op

OWNER = {"ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true", "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true",
         "TELEGRAM_OWNER_CHAT_ID": "123456", "TELEGRAM_CHAT_ID": "-100999"}


def test_rights_are_per_use_and_unknown_is_denied():
    assert op.decide("alpaca_iex", "fetch", {}).allowed is False
    assert op.decide("alpaca_iex", "fetch", OWNER).allowed is True
    assert op.decide("alpaca_iex", "publish_raw", OWNER).status == op.DENIED
    # derived results are not assumed allowed or forbidden: unverified means not published
    derived = op.decide("alpaca_iex", "publish_derived", OWNER)
    assert derived.allowed is False and derived.status == op.UNVERIFIED
    assert op.decide("alpaca_iex", "telegram_public", OWNER).allowed is False
    assert op.decide("treasury", "publish_derived", {}).allowed is True
    assert op.decide("yahoo", "fetch", OWNER).allowed is False
    assert op.decide("tradingview_widget", "publish_raw", {}).allowed is True
    assert op.decide("tradingview_widget", "compute", {}).allowed is False
    assert op.decide("made_up", "fetch", OWNER).allowed is False
    assert op.decide("treasury", "made_up_use", {}).allowed is False
    assert op.decide_all(["treasury", "alpaca_iex"], "publish_derived", OWNER).allowed is False


def test_private_delivery_only_to_a_confirmed_private_chat():
    sent = []

    def send(text, chat):
        sent.append(chat)
        return SimpleNamespace(message_id=42)

    private = lambda chat: {"type": "private"}
    group = lambda chat: {"type": "supergroup"}
    deliver = lambda env, get_chat=private: op.deliver_private("x", sources=["alpaca_iex"], env=env,
                                                                 get_chat=get_chat, send=send)
    assert deliver({**OWNER, "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "false"}) == "DENIED_BY_POLICY"
    assert deliver({k: v for k, v in OWNER.items() if k != "TELEGRAM_OWNER_CHAT_ID"}) == "OWNER_CHAT_NOT_CONFIGURED"
    assert deliver({**OWNER, "TELEGRAM_OWNER_CHAT_ID": "-100999"}) == "OWNER_CHAT_EQUALS_BROADCAST"
    assert deliver(OWNER, get_chat=group) == "DESTINATION_NOT_PRIVATE"

    def broken(chat):
        raise RuntimeError("down")

    assert deliver(OWNER, get_chat=broken) == "DESTINATION_UNVERIFIED"
    assert sent == []
    assert deliver(OWNER) == "DELIVERED" and sent == ["123456"]
