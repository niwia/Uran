# Rule: No Emojis Anywhere in Uran / Plugin

In all Uran and ASSella-related codebases:
1. **Zero Emojis**: Never use unicode emojis (such as 🚀, ⚠️, ❌, ✅, 🎮, ⚙️, etc.) in user-facing UI labels, descriptions, button text, toast notifications, error messages, or modal popups.
2. **Clean Logs and Pipes**: Never use emojis in backend logs (`logger.info`, `logger.error`), stdout/stderr, or IPC signals.
3. **Professional Typography and Native Icons**: Use clean text, SVG icons, or Decky's built-in icon components (`@decky/ui`) to indicate status, errors, warnings, or success.
4. **Clean Comments and Docs**: Source code comments, docstrings, and markdown docs must maintain professional, emoji-free technical documentation.
