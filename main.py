#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# main.py  —  entry point
#
# Usage:
#   python main.py
#
# For the self-contained single-file version:
#   python voice_assistant.py

from core.assistant import VoiceAssistant
from utils.log      import log_error


def main() -> None:
    try:
        VoiceAssistant().run()
    except KeyboardInterrupt:
        print("\n\033[90m  Interrupted.\033[0m\n")
    except Exception as exc:
        log_error(f"Fatal: {exc}")
        raise


if __name__ == "__main__":
    main()
