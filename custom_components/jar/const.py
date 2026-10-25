"""Constants for the Jar integration."""

DOMAIN = "jar"

CONF_TOKEN = "token"
CONF_URLS = "urls"
CONF_CONTROL = "allow_control"     # let Jar's memos switch things through Assist
CONF_HA_USER = "ha_user_id"        # the Home Assistant user made for Jar

HA_USER_NAME = "Jar"
SCAN_SECONDS = 30

EVENT_TASK_DONE = "jar_task_done"
EVENT_TASK_NEW = "jar_task_new"
