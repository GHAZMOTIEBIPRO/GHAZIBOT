"""Telegram Notifier with Deduplication for BLACK BOX Trading System.

Manages Telegram notifications with:
- Automatic deduplication (prevents duplicate alerts)
- Message ID tracking for updates and deletions
- Comprehensive audit logging
- Rate limiting and failure recovery
"""

from __future__ import annotations

import json
import logging
import threading
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional, Callable
from pathlib import Path
from enum import Enum

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    requests = None

logger = logging.getLogger(__name__)


class MessageStatus(Enum):
    """Status of a sent Telegram message."""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DELIVERED = "delivered"
    EDITED = "edited"
    DELETED = "deleted"
    DEDUPED = "deduped"  # Blocked by deduplication


@dataclass
class TelegramMessage:
    """Represents a Telegram message with tracking metadata."""
    message_id: Optional[int] = None
    chat_id: str = ""
    text: str = ""
    status: MessageStatus = MessageStatus.PENDING
    sent_timestamp: Optional[datetime] = None
    edited_timestamp: Optional[datetime] = None
    failed_timestamp: Optional[datetime] = None
    failure_reason: Optional[str] = None
    content_hash: str = ""  # SHA256 hash of content for deduplication
    retry_count: int = 0
    max_retries: int = 3
    content_lineage: dict[str, Any] = field(default_factory=dict)  # Source tracking
    metadata: dict[str, Any] = field(default_factory=dict)  # Additional data
    created_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        result["sent_timestamp"] = self.sent_timestamp.isoformat() if self.sent_timestamp else None
        result["edited_timestamp"] = self.edited_timestamp.isoformat() if self.edited_timestamp else None
        result["failed_timestamp"] = self.failed_timestamp.isoformat() if self.failed_timestamp else None
        result["created_timestamp"] = self.created_timestamp.isoformat()
        return result
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


class TelegramNotifier:
    """Sends and manages Telegram notifications with deduplication."""
    
    # Configuration
    TELEGRAM_API_URL = "https://api.telegram.org"
    REQUEST_TIMEOUT = 10
    MAX_RETRIES = 3
    MESSAGE_SIZE_LIMIT = 4096  # Telegram message size limit
    DEDUPE_WINDOW_MINUTES = 60  # Don't send duplicate within this time
    
    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        ledger_path: Optional[Path] = None,
        enable_deduplication: bool = True,
    ):
        """Initialize Telegram notifier.
        
        Args:
            token: Telegram bot token (from environment if not provided)
            chat_id: Telegram chat/channel ID (from environment if not provided)
            ledger_path: Path to message ledger for tracking
            enable_deduplication: Whether to deduplicate messages
        """
        import os
        
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.enable_deduplication = enable_deduplication
        
        self.ledger_path = ledger_path or Path("data/telegram/message_ledger")
        self.ledger_path.mkdir(parents=True, exist_ok=True)
        
        # Message tracking
        self._sent_messages: dict[str, TelegramMessage] = {}  # hash -> message
        self._message_ids: dict[int, TelegramMessage] = {}  # message_id -> message
        self._lock = threading.Lock()
        
        # Session with retries
        self.session = self._create_session() if requests else None
        
        # Load existing ledger
        self._load_ledger()
    
    def _create_session(self) -> requests.Session:
        """Create requests session with retry strategy."""
        if requests is None:
            return None
        
        session = requests.Session()
        retry_strategy = Retry(
            total=self.MAX_RETRIES,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
    
    def is_configured(self) -> bool:
        """Check if Telegram credentials are configured.
        
        Returns:
            True if token and chat_id are set
        """
        return bool(self.token and self.chat_id)
    
    def send(
        self,
        text: str,
        disable_web_preview: bool = True,
        content_lineage: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
        force_send: bool = False,
    ) -> TelegramMessage:
        """Send a message to Telegram with deduplication.
        
        Args:
            text: Message text
            disable_web_preview: Whether to disable link previews
            content_lineage: Source tracking information
            metadata: Additional message metadata
            force_send: Skip deduplication check
        
        Returns:
            TelegramMessage with tracking info
        """
        if not self.is_configured():
            logger.warning("Telegram not configured. Message logged but not sent.")
            return TelegramMessage(
                text=text,
                status=MessageStatus.FAILED,
                failure_reason="Telegram credentials not configured",
                content_lineage=content_lineage or {},
                metadata=metadata or {},
            )
        
        # Truncate if too long
        if len(text) > self.MESSAGE_SIZE_LIMIT:
            logger.warning(f"Message truncated from {len(text)} to {self.MESSAGE_SIZE_LIMIT} chars")
            text = text[:self.MESSAGE_SIZE_LIMIT]
        
        # Calculate content hash
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        
        # Check deduplication
        with self._lock:
            if self.enable_deduplication and not force_send:
                existing = self._sent_messages.get(content_hash)
                if existing and self._is_within_dedupe_window(existing):
                    logger.info(
                        f"Message deduplicated (hash={content_hash[:8]}..., "
                        f"original_id={existing.message_id})"
                    )
                    return TelegramMessage(
                        message_id=existing.message_id,
                        text=text,
                        status=MessageStatus.DEDUPED,
                        content_hash=content_hash,
                        content_lineage=content_lineage or {},
                        metadata=metadata or {},
                    )
            
            # Create message object
            message = TelegramMessage(
                chat_id=self.chat_id,
                text=text,
                content_hash=content_hash,
                content_lineage=content_lineage or {},
                metadata=metadata or {},
            )
            
            # Send to Telegram
            try:
                result = self._send_to_api(message, disable_web_preview)
                if result:
                    message.message_id = result
                    message.status = MessageStatus.SENT
                    message.sent_timestamp = datetime.now(timezone.utc)
                    self._sent_messages[content_hash] = message
                    self._message_ids[result] = message
                    logger.info(f"Message sent (id={result}, hash={content_hash[:8]}...)")
                else:
                    message.status = MessageStatus.FAILED
                    message.failure_reason = "No message ID returned from API"
                    message.failed_timestamp = datetime.now(timezone.utc)
            except Exception as exc:
                message.status = MessageStatus.FAILED
                message.failure_reason = str(exc)
                message.failed_timestamp = datetime.now(timezone.utc)
                logger.error(f"Failed to send message: {exc}")
            
            # Save to ledger
            self._save_message(message)
        
        return message
    
    def edit(
        self,
        message_id: int,
        new_text: str,
    ) -> bool:
        """Edit an existing Telegram message.
        
        Args:
            message_id: ID of message to edit
            new_text: New message text
        
        Returns:
            True if successful
        """
        if not self.is_configured():
            logger.warning("Telegram not configured")
            return False
        
        if not self.session:
            logger.error("No session available")
            return False
        
        try:
            url = f"{self.TELEGRAM_API_URL}/bot{self.token}/editMessageText"
            response = self.session.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "message_id": message_id,
                    "text": new_text[:self.MESSAGE_SIZE_LIMIT],
                    "disable_web_page_preview": True,
                },
                timeout=self.REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            
            # Update tracking
            with self._lock:
                if message_id in self._message_ids:
                    msg = self._message_ids[message_id]
                    msg.status = MessageStatus.EDITED
                    msg.edited_timestamp = datetime.now(timezone.utc)
                    msg.text = new_text
                    self._save_message(msg)
            
            logger.info(f"Message {message_id} edited successfully")
            return True
        
        except Exception as exc:
            logger.error(f"Failed to edit message {message_id}: {exc}")
            return False
    
    def delete(
        self,
        message_id: int,
    ) -> bool:
        """Delete a Telegram message.
        
        Args:
            message_id: ID of message to delete
        
        Returns:
            True if successful
        """
        if not self.is_configured():
            logger.warning("Telegram not configured")
            return False
        
        if not self.session:
            logger.error("No session available")
            return False
        
        try:
            url = f"{self.TELEGRAM_API_URL}/bot{self.token}/deleteMessage"
            response = self.session.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "message_id": message_id,
                },
                timeout=self.REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            
            # Update tracking
            with self._lock:
                if message_id in self._message_ids:
                    msg = self._message_ids[message_id]
                    msg.status = MessageStatus.DELETED
                    self._save_message(msg)
            
            logger.info(f"Message {message_id} deleted successfully")
            return True
        
        except Exception as exc:
            logger.error(f"Failed to delete message {message_id}: {exc}")
            return False
    
    def _send_to_api(
        self,
        message: TelegramMessage,
        disable_web_preview: bool,
    ) -> Optional[int]:
        """Send message via Telegram API.
        
        Args:
            message: TelegramMessage to send
            disable_web_preview: Whether to disable previews
        
        Returns:
            Message ID if successful, None otherwise
        """
        if not self.session:
            logger.error("No HTTP session available")
            return None
        
        url = f"{self.TELEGRAM_API_URL}/bot{self.token}/sendMessage"
        
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = self.session.post(
                    url,
                    json={
                        "chat_id": message.chat_id,
                        "text": message.text,
                        "disable_web_page_preview": disable_web_preview,
                        "parse_mode": "HTML",  # Support basic HTML formatting
                    },
                    timeout=self.REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                
                data = response.json()
                if data.get("ok"):
                    return data["result"]["message_id"]
                else:
                    error_msg = data.get("description", "Unknown error")
                    if attempt < self.MAX_RETRIES:
                        logger.warning(
                            f"Telegram API error (attempt {attempt}/{self.MAX_RETRIES}): {error_msg}"
                        )
                    else:
                        raise Exception(f"API error: {error_msg}")
            
            except Exception as exc:
                if attempt < self.MAX_RETRIES:
                    logger.warning(f"Send attempt {attempt} failed: {exc}")
                else:
                    raise
        
        return None
    
    def _is_within_dedupe_window(self, message: TelegramMessage) -> bool:
        """Check if message is within deduplication window.
        
        Args:
            message: Message to check
        
        Returns:
            True if within dedupe window
        """
        if not message.sent_timestamp:
            return False
        
        from datetime import timedelta
        age = datetime.now(timezone.utc) - message.sent_timestamp
        return age.total_seconds() < (self.DEDUPE_WINDOW_MINUTES * 60)
    
    def _save_message(self, message: TelegramMessage) -> None:
        """Save message to ledger.
        
        Args:
            message: TelegramMessage to save
        """
        try:
            msg_id = message.message_id or "pending"
            ledger_file = self.ledger_path / f"msg_{msg_id}_{message.content_hash[:8]}.json"
            ledger_file.write_text(message.to_json(), encoding="utf-8")
        except Exception as exc:
            logger.error(f"Failed to save message ledger: {exc}")
    
    def _load_ledger(self) -> None:
        """Load previous messages from ledger."""
        try:
            for ledger_file in self.ledger_path.glob("msg_*.json"):
                try:
                    data = json.loads(ledger_file.read_text(encoding="utf-8"))
                    message = TelegramMessage(**data)
                    if message.content_hash:
                        self._sent_messages[message.content_hash] = message
                    if message.message_id:
                        self._message_ids[message.message_id] = message
                except Exception as exc:
                    logger.warning(f"Failed to load ledger file {ledger_file}: {exc}")
        except Exception as exc:
            logger.warning(f"Failed to load message ledger: {exc}")
