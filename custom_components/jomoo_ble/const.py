"""Integration constants."""

DOMAIN = "jomoo_ble"
DEFAULT_PREFIX = "JOMOO_SMART_"
MANUFACTURER = "JOMOO"
MODEL = "ZS800J"
MODEL_CODE = "237369"

CONF_NAME_PREFIX = "name_prefix"
CONF_ENABLE_STATUS_STREAM = "enable_status_stream"
CONF_ENABLE_CONTROLS = "enable_controls"
CONF_ENABLE_EXPERIMENTAL = "enable_experimental"
CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = 0  # 0 = never poll; every connection makes the toilet beep
MIN_POLL_INTERVAL = 300
MAX_POLL_INTERVAL = 86400

SERVICE_REFRESH = "refresh"
SERVICE_SUSPEND = "suspend_auto_cover"
SERVICE_RESUME = "resume_auto_cover"

STORAGE_VERSION = 1
