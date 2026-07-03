"""Configuration for the Pi-friendly Discord bot.

Everything is read from environment variables (optionally via a .env file).
The design goal is that the *core* bot runs on an original Raspberry Pi or a
Pi 2 with only a handful of dependencies, so every heavyweight feature is
opt-in and guarded by a flag here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _get_id(name: str) -> int | None:
    raw = _get(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _load_dotenv() -> None:
    """Load a local .env file if python-dotenv is available.

    python-dotenv is optional. If it is not installed we fall back to a tiny
    hand-rolled parser so the bot has zero hard dependency on it.
    """
    env_path = Path(os.environ.get("BOT_ENV_FILE", ".env"))
    if not env_path.exists():
        return
    try:  # prefer the real thing when present
        from dotenv import load_dotenv

        load_dotenv(env_path)
        return
    except Exception:
        pass
    # Minimal fallback parser: KEY=VALUE, ignores comments/blank lines.
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass
class SpamConfig:
    # sliding-window message rate limit
    max_messages: int = 6
    window_seconds: float = 8.0
    # duplicate spam: same content repeated
    duplicate_limit: int = 3
    duplicate_window: float = 30.0
    # per-message caps
    max_mentions: int = 5
    max_links: int = 4
    max_emoji: int = 15
    max_newlines: int = 20
    # what to do when tripped: "delete", "timeout", "warn", "log"
    action: str = "timeout"
    timeout_seconds: int = 300


@dataclass
class ModerationConfig:
    enabled: bool = True
    # mode: off | shadow | approve | armed
    #   off     — do nothing
    #   shadow  — log what it *would* do, touch no one
    #   approve — DM the owner "ban so-and-so? yes/no" and act on the reply
    #   armed   — act automatically at the configured thresholds
    mode: str = "approve"
    approval_timeout: int = 900               # seconds a DM approval stays live
    profanity_action: str = "delete"          # delete | warn | timeout | log
    llm_escalation_enabled: bool = True
    # suspicion score below low = ignore; above high = act; between = ask LLM
    suspicion_low: float = 0.25
    suspicion_high: float = 0.75
    # LLM verdict severity that triggers each action
    llm_delete_severity: float = 0.6
    llm_timeout_severity: float = 0.8
    llm_ban_severity: float = 0.95
    llm_timeout_seconds: int = 600
    # only escalate messages at least this long (chars) — saves the Pi work
    min_escalation_len: int = 12
    # cache identical verdicts to avoid re-querying the LLM
    verdict_cache_size: int = 512


@dataclass
class LLMConfig:
    enabled: bool = True
    # OpenAI-compatible endpoint: Ollama, llama.cpp server, LM Studio, vLLM…
    base_url: str = "http://127.0.0.1:11434/v1"
    model: str = "llama3.2:1b"
    api_key: str = ""
    timeout_seconds: float = 20.0
    # keep this at 1 on a Pi 1 so you never run two inferences at once
    max_workers: int = 1
    # bounded queue; drop-and-log if the Pi falls behind
    max_queue: int = 32
    max_tokens: int = 200


@dataclass
class RankingConfig:
    enabled: bool = True
    xp_per_message: int = 5
    xp_cooldown_seconds: float = 60.0   # only earn once per cooldown
    xp_per_reaction: int = 2
    # level curve: xp needed for level n = base * n^exponent
    level_base: int = 50
    level_exponent: float = 1.6
    rep_cooldown_seconds: float = 3600.0


@dataclass
class LoggingConfig:
    enabled: bool = True
    log_channel_id: int | None = None
    log_messages: bool = False          # firehose: every message (heavy!)
    log_edits: bool = True
    log_deletes: bool = True
    log_joins: bool = True
    log_leaves: bool = True
    log_moderation: bool = True
    # auto-delete stored messages older than N days (0 = keep forever).
    # Privacy hygiene + keeps the SD/USB from filling on a busy server.
    retention_days: int = 30


@dataclass
class MetricsConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8085             # set 0 to disable HTTP but keep the status file


@dataclass
class RaidConfig:
    enabled: bool = True
    # more than `join_limit` joins within `join_window` seconds = raid
    join_limit: int = 5
    join_window: float = 20.0
    # gate accounts younger than this many hours (0 = off)
    min_account_age_hours: int = 0
    # what to do during a raid: "lockdown" | "kick" | "log"
    raid_action: str = "lockdown"
    # escalation ladder thresholds (number of warnings)
    warn_to_mute: int = 2
    warn_to_kick: int = 3
    warn_to_ban: int = 4
    mute_seconds: int = 3600
    # newline-delimited domain blocklist file for phishing links
    link_blocklist: str = ""


@dataclass
class WebadminConfig:
    enabled: bool = False        # only on capable hardware (Pi 4/5/server)
    host: str = "0.0.0.0"
    port: int = 8086
    token: str = ""              # required query token; empty = disabled
    public_url: str = ""         # domain or http://IP:port for links in emails


@dataclass
class MailerConfig:
    enabled: bool = False
    host: str = ""               # SMTP server
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = True
    from_addr: str = ""
    to_addrs: list[str] = field(default_factory=list)
    notify_on_update: bool = True
    notify_on_start: bool = False


@dataclass
class Config:
    token: str = ""
    prefix: str = "!"
    owner_ids: list[int] = field(default_factory=list)
    # everything the bot writes lives under data_dir — point this at a USB
    # stick / SSD to spare the SD card's write endurance (the real Pi killer).
    data_dir: str = "data"
    db_path: str = ""            # derived from data_dir unless BOT_DB_PATH set
    status_path: str = ""        # derived from data_dir unless BOT_STATUS_FILE set
    backup_dir: str = ""         # derived from data_dir
    # feature toggles for whole cogs
    enable_nltk: bool = False           # off by default — heavy on a Pi 1
    profanity_wordlist: str = ""        # path to custom newline-delimited list
    spam: SpamConfig = field(default_factory=SpamConfig)
    moderation: ModerationConfig = field(default_factory=ModerationConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    ranking: RankingConfig = field(default_factory=RankingConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    raid: RaidConfig = field(default_factory=RaidConfig)
    webadmin: WebadminConfig = field(default_factory=WebadminConfig)
    mailer: MailerConfig = field(default_factory=MailerConfig)

    @classmethod
    def load(cls) -> "Config":
        _load_dotenv()
        owner_ids = [
            int(x) for x in _get("BOT_OWNER_IDS").replace(",", " ").split() if x.isdigit()
        ]
        data_dir = _get("BOT_DATA_DIR", "data")
        import os.path as _p

        return cls(
            token=_get("DISCORD_TOKEN"),
            prefix=_get("BOT_PREFIX", "!"),
            owner_ids=owner_ids,
            data_dir=data_dir,
            db_path=_get("BOT_DB_PATH", _p.join(data_dir, "bot.db")),
            status_path=_get("BOT_STATUS_FILE", _p.join(data_dir, "status.json")),
            backup_dir=_get("BOT_BACKUP_DIR", _p.join(data_dir, "backups")),
            enable_nltk=_get_bool("BOT_ENABLE_NLTK", False),
            profanity_wordlist=_get("BOT_PROFANITY_WORDLIST"),
            spam=SpamConfig(
                max_messages=_get_int("SPAM_MAX_MESSAGES", 6),
                window_seconds=_get_float("SPAM_WINDOW_SECONDS", 8.0),
                duplicate_limit=_get_int("SPAM_DUPLICATE_LIMIT", 3),
                duplicate_window=_get_float("SPAM_DUPLICATE_WINDOW", 30.0),
                max_mentions=_get_int("SPAM_MAX_MENTIONS", 5),
                max_links=_get_int("SPAM_MAX_LINKS", 4),
                max_emoji=_get_int("SPAM_MAX_EMOJI", 15),
                max_newlines=_get_int("SPAM_MAX_NEWLINES", 20),
                action=_get("SPAM_ACTION", "timeout"),
                timeout_seconds=_get_int("SPAM_TIMEOUT_SECONDS", 300),
            ),
            moderation=ModerationConfig(
                enabled=_get_bool("MOD_ENABLED", True),
                mode=_get("MOD_MODE", "approve"),
                approval_timeout=_get_int("MOD_APPROVAL_TIMEOUT", 900),
                profanity_action=_get("MOD_PROFANITY_ACTION", "delete"),
                llm_escalation_enabled=_get_bool("MOD_LLM_ESCALATION", True),
                suspicion_low=_get_float("MOD_SUSPICION_LOW", 0.25),
                suspicion_high=_get_float("MOD_SUSPICION_HIGH", 0.75),
                llm_delete_severity=_get_float("MOD_LLM_DELETE_SEVERITY", 0.6),
                llm_timeout_severity=_get_float("MOD_LLM_TIMEOUT_SEVERITY", 0.8),
                llm_ban_severity=_get_float("MOD_LLM_BAN_SEVERITY", 0.95),
                llm_timeout_seconds=_get_int("MOD_LLM_TIMEOUT_SECONDS", 600),
                min_escalation_len=_get_int("MOD_MIN_ESCALATION_LEN", 12),
                verdict_cache_size=_get_int("MOD_VERDICT_CACHE_SIZE", 512),
            ),
            llm=LLMConfig(
                enabled=_get_bool("LLM_ENABLED", True),
                base_url=_get("LLM_BASE_URL", "http://127.0.0.1:11434/v1"),
                model=_get("LLM_MODEL", "llama3.2:1b"),
                api_key=_get("LLM_API_KEY"),
                timeout_seconds=_get_float("LLM_TIMEOUT_SECONDS", 20.0),
                max_workers=_get_int("LLM_MAX_WORKERS", 1),
                max_queue=_get_int("LLM_MAX_QUEUE", 32),
                max_tokens=_get_int("LLM_MAX_TOKENS", 200),
            ),
            ranking=RankingConfig(
                enabled=_get_bool("RANK_ENABLED", True),
                xp_per_message=_get_int("RANK_XP_PER_MESSAGE", 5),
                xp_cooldown_seconds=_get_float("RANK_XP_COOLDOWN", 60.0),
                xp_per_reaction=_get_int("RANK_XP_PER_REACTION", 2),
                level_base=_get_int("RANK_LEVEL_BASE", 50),
                level_exponent=_get_float("RANK_LEVEL_EXPONENT", 1.6),
                rep_cooldown_seconds=_get_float("RANK_REP_COOLDOWN", 3600.0),
            ),
            logging=LoggingConfig(
                enabled=_get_bool("LOG_ENABLED", True),
                log_channel_id=_get_id("LOG_CHANNEL_ID"),
                log_messages=_get_bool("LOG_MESSAGES", False),
                log_edits=_get_bool("LOG_EDITS", True),
                log_deletes=_get_bool("LOG_DELETES", True),
                log_joins=_get_bool("LOG_JOINS", True),
                log_leaves=_get_bool("LOG_LEAVES", True),
                log_moderation=_get_bool("LOG_MODERATION", True),
                retention_days=_get_int("LOG_RETENTION_DAYS", 30),
            ),
            metrics=MetricsConfig(
                enabled=_get_bool("METRICS_ENABLED", True),
                host=_get("METRICS_HOST", "127.0.0.1"),
                port=_get_int("METRICS_PORT", 8085),
            ),
            raid=RaidConfig(
                enabled=_get_bool("RAID_ENABLED", True),
                join_limit=_get_int("RAID_JOIN_LIMIT", 5),
                join_window=_get_float("RAID_JOIN_WINDOW", 20.0),
                min_account_age_hours=_get_int("RAID_MIN_ACCOUNT_AGE_HOURS", 0),
                raid_action=_get("RAID_ACTION", "lockdown"),
                warn_to_mute=_get_int("RAID_WARN_TO_MUTE", 2),
                warn_to_kick=_get_int("RAID_WARN_TO_KICK", 3),
                warn_to_ban=_get_int("RAID_WARN_TO_BAN", 4),
                mute_seconds=_get_int("RAID_MUTE_SECONDS", 3600),
                link_blocklist=_get("RAID_LINK_BLOCKLIST"),
            ),
            webadmin=WebadminConfig(
                enabled=_get_bool("WEBADMIN_ENABLED", False),
                host=_get("WEBADMIN_HOST", "0.0.0.0"),
                port=_get_int("WEBADMIN_PORT", 8086),
                token=_get("WEBADMIN_TOKEN"),
                public_url=_get("WEBADMIN_PUBLIC_URL"),
            ),
            mailer=MailerConfig(
                enabled=_get_bool("MAIL_ENABLED", False),
                host=_get("MAIL_HOST"),
                port=_get_int("MAIL_PORT", 587),
                username=_get("MAIL_USERNAME"),
                password=_get("MAIL_PASSWORD"),
                use_tls=_get_bool("MAIL_USE_TLS", True),
                from_addr=_get("MAIL_FROM"),
                to_addrs=[x for x in _get("MAIL_TO").replace(",", " ").split() if x],
                notify_on_update=_get_bool("MAIL_NOTIFY_ON_UPDATE", True),
                notify_on_start=_get_bool("MAIL_NOTIFY_ON_START", False),
            ),
        )
