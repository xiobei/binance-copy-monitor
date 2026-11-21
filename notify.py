"""Send a one-line phone notification (used by the restart loop)."""
import sys

import notifier

notifier.push(notifier.get_topic(), "脚本提醒", " ".join(sys.argv[1:]) or "(empty)")