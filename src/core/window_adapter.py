"""
Context-Aware Window Adapter
Inspects the active foreground Windows process to adapt formatting:
- Code / Terminal: transforms variable identifiers, snake_case, camelCase, markdown code blocks
- Chat (Slack/Discord/Teams): conversational tone, casual formatting
- Docs/Email: formal casing, punctuation, and bullet points
"""

import win32gui
import win32process
import psutil
import re
from typing import Dict, Any, Tuple

class WindowContextAdapter:
    def __init__(self):
        # Known process categories
        self._categories = {
            "code": {
                "code.exe", "cursor.exe", "windowsterminal.exe", "cmd.exe", 
                "powershell.exe", "pycharm64.exe", "idea64.exe", "devenv.exe", 
                "sublime_text.exe", "t3 code (alpha).exe", "t3 code.exe", "t3.exe", "antigravity.exe"
            },
            "chat": {
                "slack.exe", "discord.exe", "teams.exe", "ms-teams.exe", 
                "telegram.exe", "whatsapp.exe", "signal.exe"
            },
            "document": {
                "winword.exe", "outlook.exe", "notepad.exe", "notion.exe", 
                "obsidian.exe", "chrome.exe", "msedge.exe", "firefox.exe"
            }
        }

    def get_active_context(self) -> Tuple[str, str]:
        """
        Returns (category, process_name) for the current active foreground window.
        """
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return ("general", "unknown")

            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            proc_name = proc.name().lower()

            for category, processes in self._categories.items():
                if proc_name in processes:
                    return (category, proc_name)

            return ("general", proc_name)
        except Exception:
            return ("general", "unknown")

    def adapt_text(self, text: str) -> str:
        """
        Applies context-sensitive styling based on foreground window.
        """
        category, _ = self.get_active_context()

        if category == "code":
            return self._format_for_code(text)
        elif category == "chat":
            return self._format_for_chat(text)
        elif category == "document":
            return self._format_for_document(text)

        return text

    def _format_for_code(self, text: str) -> str:
        """Transforms spoken code macros like 'snake case my variable' -> 'my_variable'."""
        s = text
        boundary = r"(?=[.,;!?]|\b(?:and|or|with|then|camel\s+case|pascal\s+case|kebab\s+case|snake\s+case)\b|$)"

        # 1. snake_case
        def _to_snake(m):
            words = m.group(1).split()
            return "_".join(w.lower() for w in words)
        s = re.sub(rf"\bsnake\s+case\s+([A-Za-z0-9\s]+?)\s*{boundary}", lambda m: _to_snake(m) + " ", s, flags=re.IGNORECASE)

        # 2. camelCase
        def _to_camel(m):
            words = m.group(1).split()
            if not words:
                return ""
            return words[0].lower() + "".join(w.capitalize() for w in words[1:])
        s = re.sub(rf"\bcamel\s+case\s+([A-Za-z0-9\s]+?)\s*{boundary}", lambda m: _to_camel(m) + " ", s, flags=re.IGNORECASE)

        # 3. PascalCase
        def _to_pascal(m):
            words = m.group(1).split()
            return "".join(w.capitalize() for w in words)
        s = re.sub(rf"\bpascal\s+case\s+([A-Za-z0-9\s]+?)\s*{boundary}", lambda m: _to_pascal(m) + " ", s, flags=re.IGNORECASE)

        # 4. kebab-case
        def _to_kebab(m):
            words = m.group(1).split()
            return "-".join(w.lower() for w in words)
        s = re.sub(rf"\bkebab\s+case\s+([A-Za-z0-9\s]+?)\s*{boundary}", lambda m: _to_kebab(m) + " ", s, flags=re.IGNORECASE)

        # 5. Git commit macro: 'git commit add new feature' -> 'git commit -m "add new feature"'
        s = re.sub(r"\bgit\s+commit\s+(.+)$", r'git commit -m "\1"', s, flags=re.IGNORECASE)

        # Clean punctuation spacing
        s = re.sub(r"\s+([.,;!?])", r"\1", s).strip()
        return s

    def _format_for_chat(self, text: str) -> str:
        s = text.strip()
        if "\n" not in s and s.endswith("."):
            s = s[:-1]
        return s

    def _format_for_document(self, text: str) -> str:
        return text
