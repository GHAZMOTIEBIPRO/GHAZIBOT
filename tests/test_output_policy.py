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
    # a group or channel is never the owner's chat, even when it is the configured id or the broadcast chat
    assert deliver({**OWNER, "TELEGRAM_OWNER_CHAT_ID": "-100999"}, get_chat=group) == "DESTINATION_NOT_PRIVATE"
    assert deliver(OWNER, get_chat=group) == "DESTINATION_NOT_PRIVATE"
    assert not sent
    sent.clear()

    def broken(chat):
        raise RuntimeError("down")

    assert deliver(OWNER, get_chat=broken) == "DESTINATION_UNVERIFIED"
    assert sent == []
    assert deliver(OWNER) == "DELIVERED" and sent == ["123456"]


def test_owner_private_chat_without_a_public_channel_after_identity_check():
    """The resolved one-to-one chat is the owner's: allowed once Telegram confirms the username."""
    sent = []

    def send(text, chat):
        sent.append(chat)
        return SimpleNamespace(message_id=7)

    env = {"ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true", "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true",
           "TELEGRAM_CHAT_ID": "555", "TELEGRAM_OWNER_USERNAME": "@GhaziOwner"}
    me = lambda chat: {"type": "private", "id": 555, "username": "ghaziowner"}
    other = lambda chat: {"type": "private", "id": 555, "username": "someone_else"}
    no_name = lambda chat: {"type": "private", "id": 555}
    channel = lambda chat: {"type": "channel", "username": "ghaziowner"}
    go = lambda e, g: op.deliver_private("x", sources=["alpaca_iex"], env=e, get_chat=g, send=send)
    assert go(env, other) == "OWNER_IDENTITY_MISMATCH"
    assert go(env, no_name) == "OWNER_IDENTITY_MISMATCH"
    assert go(env, channel) == "DESTINATION_NOT_PRIVATE"
    assert not sent
    assert go(env, me) == "DELIVERED" and sent == ["555"]
    # an explicit owner id wins over the broadcast chat; the username, when set, is still checked
    sent.clear()
    assert go({**env, "TELEGRAM_OWNER_CHAT_ID": "777"}, me) == "DELIVERED" and sent == ["777"]
    # without a username, the broadcast chat is never assumed to be the owner's
    assert go({k: v for k, v in env.items() if k != "TELEGRAM_OWNER_USERNAME"}, me) == "OWNER_CHAT_NOT_CONFIGURED"
